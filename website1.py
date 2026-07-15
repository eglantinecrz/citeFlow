"""
CiteFlow AI
-----------
An intelligent, language-agnostic academic writing assistant built with Streamlit.

CiteFlow AI extracts salient keywords from a user's draft in real time, queries the
live Semantic Scholar Graph API for the most relevant scholarly paper, and lets the
user insert a properly formatted in-text citation (IEEE / APA / Harvard) directly
into their document while automatically compiling a structured bibliography.

No topic is hardcoded and no static citation database is used: every recommendation
is derived dynamically from the text the user actually writes.
"""

import re
import string
import time
from collections import Counter

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# GLOBAL CONSTANTS
# ---------------------------------------------------------------------------

SEMANTIC_SCHOLAR_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
REQUEST_TIMEOUT_SECONDS = 10
MAX_RETRY_ATTEMPTS = 4
INITIAL_BACKOFF_SECONDS = 3.0
MIN_SECONDS_BETWEEN_FETCHES = 4.0
ABSTRACT_SNIPPET_LENGTH = 250
QUOTE_SNIPPET_LENGTH = 150
MIN_PARAGRAPH_LENGTH = 100
KEYWORDS_PER_QUERY = 4

# A broad, general-purpose English stop-word list used to filter out functional
# words (articles, prepositions, auxiliary verbs, pronouns, conjunctions, etc.)
# so that only semantically dense, topic-carrying terms remain for the query.
ENGLISH_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it", "its",
    "itself", "let's", "me", "more", "most", "mustn't", "my", "myself", "no",
    "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "should", "shouldn't", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasn't", "we", "were", "weren't", "what", "when", "where", "which", "while",
    "who", "whom", "why", "with", "won't", "would", "wouldn't", "you", "your",
    "yours", "yourself", "yourselves", "also", "however", "thus", "therefore",
    "may", "might", "must", "shall", "will", "within", "without", "upon",
    "towards", "among", "across", "via", "per", "using", "used", "use", "based",
    "including", "include", "includes", "one", "two", "three", "new", "novel",
    "study", "paper", "research", "approach", "method", "methods", "results",
    "conclusion", "introduction", "abstract", "furthermore", "moreover",
    "although", "despite", "several", "various", "significant", "significantly",
}

# Structural line patterns (headings) that should never be treated as body
# paragraphs eligible for citation, regardless of their length.
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
# NLP PROCESSING LAYER
# ---------------------------------------------------------------------------


def tokenize_text(raw_text: str) -> list:
    """
    Convert raw text into a clean list of lowercase tokens.

    Punctuation is stripped except for internal hyphens, which are preserved
    because hyphenated compounds (e.g. "zero-trust", "cyber-physical") are
    typically highly informative academic terms.
    """
    lowered_text = raw_text.lower()
    # Match word sequences that may contain internal hyphens, discarding
    # any other punctuation or symbols encountered in the source text.
    raw_tokens = re.findall(r"[a-z]+(?:-[a-z]+)*", lowered_text)
    return raw_tokens


def extract_keywords(paragraph_text: str, top_n: int = KEYWORDS_PER_QUERY) -> list:
    """
    Dynamically isolate the most informative, distinct keywords from a text
    segment using a lightweight, language-agnostic scoring heuristic:

      1. Tokenize and lowercase the input while preserving hyphenation.
      2. Discard stop-words and overly short tokens.
      3. Score each unique token by a weighted combination of:
           - hyphenation (compound academic terms score higher),
           - token length (longer, more specific terms score higher),
           - frequency within the segment.
      4. Return the top-N highest scoring, distinct tokens.

    No static topic-to-keyword mapping is used; the result is fully derived
    from the statistical and morphological properties of the input text.
    """
    tokens = tokenize_text(paragraph_text)

    # Remove stop-words and trivially short, non-hyphenated tokens.
    filtered_tokens = [
        token for token in tokens
        if token not in ENGLISH_STOPWORDS and (len(token) > 3 or "-" in token)
    ]

    if not filtered_tokens:
        return []

    token_frequencies = Counter(filtered_tokens)

    def score_token(token: str) -> float:
        hyphenation_bonus = 5.0 if "-" in token else 0.0
        length_bonus = min(len(token), 15) * 0.3
        frequency_bonus = token_frequencies[token] * 1.5
        return hyphenation_bonus + length_bonus + frequency_bonus

    # Rank distinct tokens by descending score, breaking ties alphabetically
    # for deterministic, reproducible query construction.
    distinct_tokens = sorted(
        set(filtered_tokens),
        key=lambda token: (-score_token(token), token),
    )

    return distinct_tokens[:top_n]


def split_into_paragraphs(document_text: str) -> list:
    """
    Split the full document into raw blocks separated by blank lines.

    Returns the complete list of blocks (including headings and short
    fragments) so that the original document structure can be losslessly
    reconstructed after a citation is inserted into a specific block.
    """
    blocks = re.split(r"\n\s*\n", document_text.strip("\n"))
    return blocks


def is_citable_paragraph(block_text: str) -> bool:
    """
    Determine whether a text block qualifies as a citable body paragraph.

    Structural headings (e.g. "Introduction:") and any fragment shorter than
    the configured minimum length are excluded from citation targeting.
    """
    stripped_block = block_text.strip()
    if len(stripped_block) < MIN_PARAGRAPH_LENGTH:
        return False
    for heading_pattern in HEADING_PATTERNS:
        if re.match(heading_pattern, stripped_block.lower()):
            return False
    return True


# ---------------------------------------------------------------------------
# LIVE ACADEMIC DATABASE INTEGRATION LAYER
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False, ttl=600)
def fetch_top_paper_cached(search_query: str, api_key: str = ""):
    """
    Cached wrapper around the raw Semantic Scholar request. Streamlit caches
    the result per unique (query, api_key) pair for 10 minutes, so re-selecting
    the same paragraph (or re-running the app) does not re-hit the rate-limited
    public endpoint unnecessarily.

    Returns a tuple of (paper_dict, error_message), exactly as fetch_top_paper.
    """
    request_params = {
        "query": search_query,
        "limit": 1,
        "fields": "title,authors,venue,year,abstract,url",
    }
    # A descriptive User-Agent is required by many Semantic Scholar edge
    # nodes; requests' default UA is sometimes deprioritized under load.
    request_headers = {"User-Agent": "CiteFlowAI/1.0 (Academic Writing Assistant)"}
    # An optional personal API key (free from Semantic Scholar) raises the
    # rate limit well above the shared, unauthenticated tier.
    if api_key:
        request_headers["x-api-key"] = api_key

    last_error_message = None

    for attempt_number in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(
                SEMANTIC_SCHOLAR_ENDPOINT,
                params=request_params,
                headers=request_headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            # Rate limiting: back off exponentially and retry rather than
            # failing immediately, since the public, unauthenticated tier
            # allows roughly one request per second and is shared across
            # all anonymous callers.
            if response.status_code == 429:
                last_error_message = (
                    "Semantic Scholar's public API is rate-limiting requests "
                    "(HTTP 429). This is common on the free, unauthenticated "
                    "tier when requests arrive in quick succession."
                )
                if attempt_number < MAX_RETRY_ATTEMPTS:
                    # Exponential backoff: waits grow as 3s, 12s, 27s, ...
                    time.sleep(INITIAL_BACKOFF_SECONDS * (attempt_number ** 2))
                    continue
                return None, last_error_message + " Please wait about 30 seconds and try again."

            if response.status_code == 503:
                last_error_message = "Semantic Scholar is temporarily unavailable (HTTP 503)."
                if attempt_number < MAX_RETRY_ATTEMPTS:
                    time.sleep(INITIAL_BACKOFF_SECONDS * (attempt_number ** 2))
                    continue
                return None, last_error_message + " Please try again shortly."

            response.raise_for_status()
            payload = response.json()

            results = payload.get("data", [])
            if not results:
                return None, "No matching papers were found for the extracted keywords."
            return results[0], None

        except requests.exceptions.Timeout:
            last_error_message = "The request to Semantic Scholar timed out."
        except requests.exceptions.ConnectionError:
            last_error_message = "Unable to reach Semantic Scholar. Please check your network connection."
        except requests.exceptions.HTTPError as http_error:
            return None, f"Semantic Scholar returned an error: {http_error}"
        except requests.exceptions.RequestException as generic_error:
            return None, f"An unexpected network error occurred: {generic_error}"

        if attempt_number < MAX_RETRY_ATTEMPTS:
            time.sleep(INITIAL_BACKOFF_SECONDS * (attempt_number ** 2))

    return None, last_error_message or "The request failed after multiple attempts."


def fetch_top_paper(search_query: str):
    """
    Public entry point for retrieving the single most relevant paper for a
    dynamically generated keyword query, delegating to the cached, retrying
    implementation so repeated lookups stay within Semantic Scholar's
    rate limits. Automatically forwards an optional user-supplied API key.

    Returns a tuple of (paper_dict, error_message). Exactly one of the two
    will be populated: paper_dict on success, error_message on failure.
    """
    return fetch_top_paper_cached(search_query, st.session_state.semantic_scholar_api_key)


# ---------------------------------------------------------------------------
# CITATION & BIBLIOGRAPHY FORMATTING LAYER
# ---------------------------------------------------------------------------


def get_first_author_surname(paper: dict) -> str:
    """Extract the surname of the first listed author, falling back safely."""
    authors = paper.get("authors") or []
    if not authors:
        return "Unknown"
    full_name = authors[0].get("name", "Unknown").strip()
    name_parts = full_name.split()
    return name_parts[-1] if name_parts else "Unknown"


def get_all_author_names(paper: dict) -> str:
    """Return a comma-separated string of all author full names."""
    authors = paper.get("authors") or []
    if not authors:
        return "Unknown Author"
    return ", ".join(author.get("name", "Unknown") for author in authors)


def build_inline_tag(paper: dict, citation_style: str, ieee_number: int) -> str:
    """
    Build the short inline citation marker for the given style:
      - IEEE:            [n]
      - APA / Harvard:   (Surname, Year)
    """
    if citation_style == "IEEE":
        return f"[{ieee_number}]"
    publication_year = paper.get("year") or "n.d."
    return f"({get_first_author_surname(paper)}, {publication_year})"


def build_inline_citation_text(paper: dict, citation_style: str, insertion_mode: str, ieee_number: int) -> str:
    """
    Compose the exact string to be appended to the target paragraph, based
    on the user's chosen insertion mode:
      - "Only Citation":            just the inline tag.
      - "Insert Quote + Citation":  a truncated abstract snippet as a quote,
                                     followed by the inline tag.
    """
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
    """
    Compose the full, style-compliant reference-list entry for a paper.
    """
    author_names = get_all_author_names(paper)
    title = paper.get("title") or "Untitled work"
    venue = paper.get("venue") or "Unknown venue"
    year = paper.get("year") or "n.d."
    url = paper.get("url") or ""

    if citation_style == "IEEE":
        return f'[{ieee_number}] {author_names}, "{title}," {venue}, {year}. Available: {url}'
    elif citation_style == "APA":
        return f"{author_names} ({year}). {title}. {venue}. {url}"
    else:  # Harvard
        return f"{author_names} ({year}) '{title}', {venue}. Available at: {url}"


# ---------------------------------------------------------------------------
# STREAMLIT SESSION STATE INITIALIZATION
# ---------------------------------------------------------------------------


def initialize_session_state() -> None:
    """Ensure all required session-state keys exist before first render."""
    if "editor_text" not in st.session_state:
        st.session_state.editor_text = DEFAULT_DOCUMENT_TEXT

    if "bibliography_entries" not in st.session_state:
        # Maps a paper's URL (unique key) -> its assigned bibliography record.
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

    if "semantic_scholar_api_key" not in st.session_state:
        st.session_state.semantic_scholar_api_key = ""

    if "last_fetch_timestamp" not in st.session_state:
        st.session_state.last_fetch_timestamp = 0.0


def get_next_ieee_number() -> int:
    """Return the next sequential IEEE numeric marker."""
    return len(st.session_state.bibliography_entries) + 1


def register_bibliography_entry(paper: dict, citation_style: str) -> int:
    """
    Register a paper in the persistent bibliography if not already present,
    reusing its previously assigned IEEE number when applicable. Returns the
    numeric identifier associated with the paper (used for IEEE markers).
    """
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
    """Render the global configuration sidebar."""
    with st.sidebar:
        st.title("⚙️ CiteFlow AI Settings")
        st.markdown("Configure global citation preferences for this session.")

        st.session_state.citation_style = st.selectbox(
            "Academic Citation Style",
            options=["IEEE", "APA", "Harvard"],
            index=["IEEE", "APA", "Harvard"].index(st.session_state.citation_style),
            help="Determines the format of both inline citations and the bibliography.",
        )

        st.divider()
        st.markdown("**Semantic Scholar API Key (optional)**")
        st.session_state.semantic_scholar_api_key = st.text_input(
            "API key",
            value=st.session_state.semantic_scholar_api_key,
            type="password",
            label_visibility="collapsed",
            placeholder="Paste your free API key to raise rate limits",
            help="Get a free key at semanticscholar.org/product/api. "
                 "Without one, requests share a low public rate limit.",
        )

        st.divider()
        st.markdown("**About CiteFlow AI**")
        st.caption(
            "CiteFlow AI dynamically extracts keywords from your writing and "
            "queries the live Semantic Scholar API to surface relevant "
            "scholarly sources in real time — no static topic database involved."
        )

        st.divider()
        if st.button("🗑️ Clear Bibliography", use_container_width=True):
            st.session_state.bibliography_entries = {}
            st.rerun()


def render_editor_column() -> None:
    """Render the left-hand document editor and generated bibliography."""
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
        # Sort entries by their assigned numeric order for stable display.
        sorted_entries = sorted(
            st.session_state.bibliography_entries.values(),
            key=lambda entry: entry["number"],
        )
        with st.container(border=True):
            for entry in sorted_entries:
                st.markdown(entry["reference"])


def render_recommendation_column() -> None:
    """Render the right-hand live recommendation and citation panel."""
    st.subheader("🔎 Live Recommendation Panel")

    all_blocks = split_into_paragraphs(st.session_state.editor_text)
    citable_indices = [i for i, block in enumerate(all_blocks) if is_citable_paragraph(block)]

    if not citable_indices:
        st.warning(
            "No eligible body paragraphs detected yet. Write a paragraph of at "
            f"least {MIN_PARAGRAPH_LENGTH} characters to enable recommendations."
        )
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

    fetch_button_clicked = st.button("🔍 Fetch Relevant Paper", use_container_width=True, type="primary")

    if fetch_button_clicked:
        seconds_since_last_fetch = time.time() - st.session_state.last_fetch_timestamp

        if seconds_since_last_fetch < MIN_SECONDS_BETWEEN_FETCHES:
            wait_remaining = round(MIN_SECONDS_BETWEEN_FETCHES - seconds_since_last_fetch, 1)
            st.session_state.fetch_error = (
                f"Please wait {wait_remaining}s before fetching again — this "
                "avoids tripping Semantic Scholar's public rate limit."
            )
        else:
            st.session_state.last_fetch_timestamp = time.time()
            target_paragraph = all_blocks[selected_block_index]
            extracted_keywords = extract_keywords(target_paragraph)

            if not extracted_keywords:
                st.session_state.fetched_paper = None
                st.session_state.fetch_error = "Could not extract meaningful keywords from this paragraph."
            else:
                search_query = " ".join(extracted_keywords)
                st.session_state.active_query = search_query
                with st.spinner(f"Searching Semantic Scholar for: {search_query}"):
                    paper_result, error_message = fetch_top_paper(search_query)
                st.session_state.fetched_paper = paper_result
                st.session_state.fetch_error = error_message

    # Persist which paragraph is currently targeted for a potential insertion.
    st.session_state.selected_paragraph_index = selected_block_index

    if st.session_state.active_query:
        st.caption(f"Last query: `{st.session_state.active_query}`")

    if st.session_state.fetch_error:
        st.error(st.session_state.fetch_error)

    if st.session_state.fetched_paper:
        render_paper_card(st.session_state.fetched_paper, selected_block_index, all_blocks)


def render_paper_card(paper: dict, target_block_index: int, all_blocks: list) -> None:
    """Render the fetched paper's metadata along with citation controls."""
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
            st.markdown(f"[🔗 View on Semantic Scholar]({paper_url})")

        st.divider()

        insertion_mode = st.selectbox(
            "Inline citation format:",
            options=["Only Citation", "Insert Quote + Citation"],
            key="insertion_mode_selector",
        )

        insert_clicked = st.button("➕ Insert Citation", use_container_width=True)

        if insert_clicked:
            insert_citation_into_document(paper, target_block_index, all_blocks, insertion_mode)


def insert_citation_into_document(paper: dict, target_block_index: int, all_blocks: list, insertion_mode: str) -> None:
    """
    Append the computed inline citation to the targeted paragraph, register
    the paper in the persistent bibliography, and stage the updated document
    text for application on the next rerun. The editor's session-state key is
    owned by the text_area widget, which has already been instantiated
    earlier in this script run, so it cannot be written to directly here.
    """
    citation_style = st.session_state.citation_style

    # Register (or retrieve) this paper's bibliography entry first so that
    # the IEEE numeric marker used inline matches the reference list.
    assigned_number = register_bibliography_entry(paper, citation_style)

    inline_citation_text = build_inline_citation_text(
        paper, citation_style, insertion_mode, assigned_number
    )

    updated_blocks = list(all_blocks)
    updated_blocks[target_block_index] = updated_blocks[target_block_index].rstrip() + inline_citation_text

    # Stage the new text; it is applied to the widget key at the top of the
    # next run, before the text_area widget is re-instantiated.
    st.session_state.pending_editor_text = "\n\n".join(updated_blocks)
    st.success("Citation inserted successfully.")
    st.rerun()


# ---------------------------------------------------------------------------
# APPLICATION ENTRY POINT
# ---------------------------------------------------------------------------


def main() -> None:
    """Configure the page and orchestrate the full CiteFlow AI layout."""
    st.set_page_config(
        page_title="CiteFlow AI",
        page_icon="🧠",
        layout="wide",
    )

    initialize_session_state()

    # Apply any citation insertion staged on the previous run BEFORE the
    # text_area widget below is instantiated. Writing to a widget-bound
    # session-state key after that widget has already been drawn raises
    # StreamlitAPIException, so the update must land here instead.
    if st.session_state.pending_editor_text is not None:
        st.session_state.editor_text = st.session_state.pending_editor_text
        st.session_state.pending_editor_text = None

    st.title("🧠 CiteFlow AI")
    st.caption("An intelligent, language-agnostic academic writing assistant powered by live scholarly search.")

    render_sidebar()

    editor_col, recommendation_col = st.columns([3, 2], gap="large")

    with editor_col:
        render_editor_column()

    with recommendation_col:
        render_recommendation_column()


if __name__ == "__main__":
    main()