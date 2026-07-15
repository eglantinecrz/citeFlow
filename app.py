import streamlit as st
import docx
from pypdf import PdfReader
import io

# Fonction pour charger le CSS
def load_css():
    with open("style.css", "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

def extract_text(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".txt"): return uploaded_file.read().decode("utf-8")
    if name.endswith(".docx"): 
        doc = docx.Document(uploaded_file)
        return "\n".join([p.text for p in doc.paragraphs])
    if name.endswith(".pdf"):
        reader = PdfReader(uploaded_file)
        return "\n".join([page.extract_text() for page in reader.pages])
    return ""

def main():
    st.set_page_config(layout="wide")
    load_css()
    
    st.title("🧠 CiteFlow AI")
    st.markdown('<div class="citeflow-tagline">Your academic writing assistant, simplified ✨</div>', unsafe_allow_html=True)
    
    if "text" not in st.session_state: st.session_state.text = ""
    
    with st.sidebar:
        st.subheader("📂 Import Document")
        up = st.file_uploader("Upload", type=["txt", "docx", "pdf"])
        if up: st.session_state.text = extract_text(up)
            
    col1, col2 = st.columns([3, 2])
    with col1:
        st.text_area("Editor", key="text", height=400, label_visibility="collapsed")
    with col2:
        st.subheader("🔎 Recommendations")
        if st.button("Analyze Paragraph"):
            st.info("Analysis logic here...")

if __name__ == "__main__":
    main()
