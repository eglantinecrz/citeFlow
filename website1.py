"""
CiteFlow AI (OpenAI & Crossref Edition)
-----------
An intelligent, language-agnostic academic writing assistant built with Streamlit.
"""

import re
import time
import requests
import streamlit as st
from openai import OpenAI

# ---------------------------------------------------------------------------
# GLOBAL CONSTANTS
# ---------------------------------------------------------------------------

CROSSREF_ENDPOINT = "https://api.crossref.org/works"
ABSTRACT_SNIPPET_LENGTH = 250
QUOTE_SNIPPET_LENGTH = 150
MIN_PARAGRAPH_LENGTH = 100
KEYWORDS_PER_QUERY = 4

# Structural line patterns (headings) that should never be treated as body
# paragraphs eligible for citation, regardless of their length[cite: 3].
HEADING_PATTERNS = [
    r"^introduction\s*:?\s*$",
    r"^conclusion\s*:?\s*$",
    r"^abstract\s*:?\s*$",
    r"^methodology\s*:?\s*$",
    r"^results\s*:?\s*$",
    r"^discussion\s*:?\s*$",
    r"^references\s*:?\s*$",
    r"^background\s*:?\s*$",
]

DEFAULT_DOCUMENT_TEXT = """Introduction:

The convergence of operational technology and information technology has exposed industrial control systems to unprecedented cybersecurity risks. Modern cyber-physical systems increasingly adopt zero-trust architectures to mitigate lateral movement attacks, yet the integration of legacy SCADA protocols with cloud-based analytics introduces persistent vulnerabilities that adversaries can exploit through supply-chain compromise and firmware manipulation. Robust anomaly-detection frameworks combined with continuous authentication are now considered essential safeguards for critical infrastructure resilience.

Autonomous Vehicles:

Perception pipelines in autonomous vehicles rely heavily on multi-modal sensor fusion, combining LiDAR point clouds, radar returns, and high-resolution camera imagery to construct a coherent three-dimensional understanding of the driving environment. Recent advances in real-time deep-learning inference have enabled onboard computer-vision systems to perform object detection and trajectory prediction with sub-hundred-millisecond latency, although occlusion handling and adverse-weather robustness remain open engineering challenges for large-scale deployment.

Biotechnology:

Enzyme engineering through directed evolution has transformed industrial biocatalysis by allowing researchers to iteratively optimize protein stability, substrate specificity, and catalytic turnover without requiring complete a priori knowledge of the underlying protein-folding landscape. Coupling high-throughput screening with machine-learning-guided mutagenesis has accelerated the discovery of thermostable enzyme variants suitable for industrial-scale biomanufacturing under non-native reaction conditions.
"""

# ---------------------------------------------------------------------------
# NLP PROCESSING LAYER (OPENAI)
# ---------------------------------------------------------------------------

def extract_keywords(paragraph_text: str, top_n: int = KEYWORDS_PER_QUERY) -> list:
    """
    Analyse le texte avec OpenAI pour en extraire de véritables concepts clés.
    """
    try:
        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        
        prompt = (
            f"Extract exactly {top_n} highly relevant academic search keywords "
            f"or short compound phrases from the following text. "
            f"Return ONLY the keywords separated by commas, nothing else.\n\n"
            f"Text: {paragraph_text}"
        )
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert academic librarian."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        
        raw_result = response.choices[0].message.content
        keywords = [kw.strip() for kw in raw_result.split(',')]
        
        return keywords[:top_n]
        
    except Exception as e:
        st.error(f"Erreur de communication avec OpenAI : {e}")
        return []

def split_into_paragraphs(document_text: str) -> list:
    """
    Split the full document into raw blocks separated by blank lines[cite: 3].
    """
    blocks = re.split(r"\n\s*\n", document_text.strip("\n"))
    return blocks

def is_citable_paragraph(block_text: str) -> bool:
    """
    Determine whether a text block qualifies as a citable body paragraph[cite: 3].
    """
    stripped_block = block_text.strip()
    if len(stripped_block) < MIN_PARAGRAPH_LENGTH:
        return False
    for heading_pattern in HEADING_PATTERNS:
        if re.match(heading_pattern, stripped_block.lower()):
            return False
    return True

# ---------------------------------------------------------------------------
# LIVE ACADEMIC DATABASE INTEGRATION LAYER (CROSSREF)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=600)
def fetch_top_paper_cached(search_query: str):
    """
    Interroge l'API de Crossref. Aucune clé API n'est requise.
    """
    request_params = {
        "query": search_query,
        "rows": 1,
        "select": "title,author,issued,container-title,abstract,URL"
    }
    
    # N'hésitez pas à remplacer par votre propre adresse email pour optimiser la vitesse de Crossref
    request_headers = {
        "User-Agent": "CiteFlowAI/1.0 (mailto:contact@exemple.com)"
    }

    try:
        response = requests.get(
            CROSSREF_ENDPOINT,
            params=request_params,
            headers=request_headers,
            timeout=10,
        )
        
        response.raise_for_status()
        data = response.json()
        
        items = data.get("message", {}).get("items", [])
        if not items:
            return None, "Aucun article trouvé sur Crossref pour ces mots-clés."
            
        item = items[0]
        
        authors_list = []
        for a in item.get("author", []):
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                authors_list.append({"name": name})
                
        year = "n.d."
        try:
            year = item.get("issued", {}).get("date-parts", [[None]])[0][0]
        except Exception:
            pass
            
        raw_abstract = item.get("abstract", "Aucun résumé disponible pour cet article.")
        clean_abstract = re.sub(r'<[^>]+>', '', raw_abstract)

        paper_dict = {
            "title": item.get("title", ["Titre inconnu"])[0],
            "authors": authors_list,
            "venue": item.get("container-title", ["Revue inconnue"])[0],
            "year": year,
            "abstract": clean_abstract,
            "url": item.get("URL", "")
        }
        
        return paper_dict, None
        
    except requests.exceptions.RequestException as e:
        return None, f"Erreur réseau avec Crossref : {e}"

def fetch_top_paper(search_query: str):
    return fetch_top_paper_cached(search_query)

# ---------------------------------------------------------------------------
# CITATION & BIBLIOGRAPHY FORMATTING LAYER
# ---------------------------------------------------------------------------

def get_first_author_surname(paper: dict) -> str:
    authors = paper.get("authors") or []
    if not authors:
        return "Unknown"
    full_name = authors[0].get("name", "Unknown").strip()
    name_parts = full_name.split()
    return name_parts[-1] if name_parts else "Unknown"

def get_all_author_names(paper: dict) -> str:
    authors = paper.get("authors") or []
    if not authors:
        return "Unknown Author"
    return ", ".join(author.get("name", "Unknown") for author in authors)

def build_inline_tag(paper: dict, citation_style: str, ieee_number: int) -> str:
    if citation_style == "IEEE":
        return f"[{ieee_number}]"
    publication_year = paper.get("year") or "n.d."
    return f"({get_first_author_surname(paper)}, {publication_year})"

def build_inline_citation_text(paper: dict, citation_style: str, insertion_mode: str, ieee_number: int) -> str:
    inline_tag = build_inline_tag(paper, citation_style, ieee_number)
    if insertion_mode == "Insert Quote + Citation":
        abstract_text = paper.get("abstract") or ""
        if len(abstract_text) > QUOTE_SNIPPET_LENGTH:
            quote_snippet = abstract_text[:QUOTE_SNIPPET_LENGTH].rstrip() + "..."
        else:
            quote_snippet = abstract_text if abstract_text else "No abstract available"
        return f' "{quote_snippet}" {inline_tag}'
    return f" {inline_tag}"

def build_bibliography_entry(paper: dict, citation_style: str, ieee_number: int) -> str:
    author_names = get_all_author_names(paper)
    title = paper.get("title") or "Untitled work"
    venue = paper.get("venue") or "Unknown venue"
    year = paper.get("year") or "n.d."
    url = paper.get("url") or ""

    if citation_style == "IEEE":
        return f'[{ieee_number}] {author_names}, "{title}," {venue}, {year}. Available: {url}'
    elif citation_style == "APA":
        return f"{author_names} ({year}). {title}. {venue}. {url}"
    else:
        return f"{author_names} ({year}) '{title}', {venue}. Available at: {url}"

# ---------------------------------------------------------------------------
# STREAMLIT SESSION STATE INITIALIZATION
# ---------------------------------------------------------------------------

def initialize_session_state() -> None:
    if "editor_text" not in st.session_state:
        st.session_state.editor_text = DEFAULT_DOCUMENT_TEXT
    if "bibliography_entries" not in st.session_state:
        st.session_state.bibliography_entries = {}
    if "citation_style" not in st.session_state:
        st.session_state.citation_style = "IEEE"
    if "fetched_paper" not in st.session_state:
        st.session_state.fetched_paper = None
    if "fetch_error" not in st.session_state:
        st.session_state.fetch_error = None
    if "active_query" not in st.session_state:
        st.session_state.active_query = ""
    if "pending_editor_text" not in st.session_state:
        st.session_state.pending_editor_text = None
    if "last_fetch_timestamp" not in st.session_state:
        st.session_state.last_fetch_timestamp = 0.0

def get_next_ieee_number() -> int:
    return len(st.session_state.bibliography_entries) + 1

def register_bibliography_entry(paper: dict, citation_style: str) -> int:
    paper_key = paper.get("url") or paper.get("title", "unknown-paper")
    if paper_key in st.session_state.bibliography_entries:
        existing_entry = st.session_state.bibliography_entries[paper_key]
        return existing_entry["number"]
    
    assigned_number = get_next_ieee_number()
    reference_string = build_bibliography_entry(paper, citation_style, assigned_number)
    
    st.session_state.bibliography_entries[paper_key] = {
        "number": assigned_number,
        "reference": reference_string,
        "style": citation_style,
    }
    return assigned_number

# ---------------------------------------------------------------------------
# STREAMLIT APPLICATION LAYOUT
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.title("⚙️ CiteFlow AI Settings")
        st.markdown("Configure global citation preferences for this session.")
        st.session_state.citation_style = st.selectbox(
            "Academic Citation Style",
            options=["IEEE", "APA", "Harvard"],
            index=["IEEE", "APA", "Harvard"].index(st.session_state.citation_style),
        )
        st.divider()
        st.markdown("**About CiteFlow AI**")
        st.caption(
            "CiteFlow AI uses OpenAI to intelligently analyze your draft, and queries "
            "the open Crossref database to surface relevant scholarly sources in real time."
        )
        st.divider()
        if st.button("🗑️ Clear Bibliography", use_container_width=True):
            st.session_state.bibliography_entries = {}
            st.rerun()

def render_editor_column() -> None:
    st.subheader("📝 Document Editor")
    st.text_area(
        label="Write or paste your academic draft below:",
        key="editor_text",
        height=420,
        label_visibility="collapsed",
    )
    st.subheader("📚 Generated Bibliography")
    if not st.session_state.bibliography_entries:
        st.info("No citations inserted yet. Insert a citation to populate your bibliography.")
    else:
        sorted_entries = sorted(
            st.session_state.bibliography_entries.values(),
            key=lambda entry: entry["number"],
        )
        with st.container(border=True):
            for entry in sorted_entries:
                st.markdown(entry["reference"])

def render_recommendation_column() -> None:
    st.subheader("🔎 Live Recommendation Panel")
    all_blocks = split_into_paragraphs(st.session_state.editor_text)
    citable_indices = [i for i, block in enumerate(all_blocks) if is_citable_paragraph(block)]
    if not citable_indices:
        st.warning(f"Write a paragraph of at least {MIN_PARAGRAPH_LENGTH} characters to enable recommendations.")
        return

    def format_paragraph_label(block_index: int) -> str:
        preview_text = all_blocks[block_index].strip().replace("\n", " ")
        truncated_preview = preview_text[:60] + ("..." if len(preview_text) > 60 else "")
        return f"Paragraph {citable_indices.index(block_index) + 1}: {truncated_preview}"

    selected_block_index = st.selectbox(
        "Select a paragraph to analyze:",
        options=citable_indices,
        format_func=format_paragraph_label,
    )

    if st.button("🔍 Fetch Relevant Paper", use_container_width=True, type="primary"):
        st.session_state.last_fetch_timestamp = time.time()
        target_paragraph = all_blocks[selected_block_index]
        
        with st.spinner("OpenAI is analyzing your text..."):
            extracted_keywords = extract_keywords(target_paragraph)

        if not extracted_keywords:
            st.session_state.fetched_paper = None
            st.session_state.fetch_error = "Could not extract meaningful keywords from this paragraph."
        else:
            search_query = " ".join(extracted_keywords)
            st.session_state.active_query = search_query
            with st.spinner(f"Searching Crossref for: {search_query}"):
                paper_result, error_message = fetch_top_paper(search_query)
            st.session_state.fetched_paper = paper_result
            st.session_state.fetch_error = error_message

    st.session_state.selected_paragraph_index = selected_block_index

    if st.session_state.active_query:
        st.caption(f"Last query: `{st.session_state.active_query}`")
    if st.session_state.fetch_error:
        st.error(st.session_state.fetch_error)
    if st.session_state.fetched_paper:
        render_paper_card(st.session_state.fetched_paper, selected_block_index, all_blocks)

def render_paper_card(paper: dict, target_block_index: int, all_blocks: list) -> None:
    with st.container(border=True):
        st.markdown(f"**{paper.get('title', 'Untitled work')}**")
        authors_list = paper.get("authors") or []
        author_display = get_all_author_names(paper) if authors_list else "Unknown Author"
        st.caption(f"👤 {author_display}")
        venue_text = paper.get("venue") or "Unknown venue"
        year_text = paper.get("year") or "n.d."
        st.markdown(f"🏛️ **Venue:** {venue_text}  &nbsp;|&nbsp; 📅 **Year:** {year_text}")
        abstract_text = paper.get("abstract") or "No abstract available for this paper."
        abstract_snippet = abstract_text[:ABSTRACT_SNIPPET_LENGTH]
        if len(abstract_text) > ABSTRACT_SNIPPET_LENGTH:
            abstract_snippet += "..."
        st.markdown(f"📄 *{abstract_snippet}*")
        paper_url = paper.get("url")
        if paper_url:
            st.markdown(f"[🔗 View on Crossref]({paper_url})")
        st.divider()
        insertion_mode = st.selectbox(
            "Inline citation format:",
            options=["Only Citation", "Insert Quote + Citation"],
            key="insertion_mode_selector",
        )
        if st.button("➕ Insert Citation", use_container_width=True):
            insert_citation_into_document(paper, target_block_index, all_blocks, insertion_mode)

def insert_citation_into_document(paper: dict, target_block_index: int, all_blocks: list, insertion_mode: str) -> None:
    citation_style = st.session_state.citation_style
    assigned_number = register_bibliography_entry(paper, citation_style)
    inline_citation_text = build_inline_citation_text(paper, citation_style, insertion_mode, assigned_number)
    
    updated_blocks = list(all_blocks)
    updated_blocks[target_block_index] = updated_blocks[target_block_index].rstrip() + inline_citation_text
    
    st.session_state.pending_editor_text = "\n\n".join(updated_blocks)
    st.success("Citation inserted successfully.")
    st.rerun()

# ---------------------------------------------------------------------------
# APPLICATION ENTRY POINT
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="CiteFlow AI", page_icon="🧠", layout="wide")
    initialize_session_state()

    if st.session_state.pending_editor_text is not None:
        st.session_state.editor_text = st.session_state.pending_editor_text
        st.session_state.pending_editor_text = None

    st.title("🧠 CiteFlow AI")
    st.caption("An intelligent academic writing assistant powered by OpenAI and Crossref.")

    render_sidebar()
    
    editor_col, recommendation_col = st.columns([3, 2], gap="large")

    with editor_col:
        render_editor_column()
    with recommendation_col:
        render_recommendation_column()

if __name__ == "__main__":
    main()
