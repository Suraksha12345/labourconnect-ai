import os

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

BASE_DIR = os.path.dirname(__file__)
KB_DIR = os.path.join(BASE_DIR, "knowledge_base")
DB_DIR = os.path.join(BASE_DIR, "chroma_db")

CATEGORIES = ["schemes", "laws", "safety", "registration", "faqs", "policies"]

def load_all_documents():
    all_docs = []
    for category in CATEGORIES:
        folder = os.path.join(KB_DIR, category)
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            path = os.path.join(folder, fname)
            if fname.lower().endswith(".pdf"):
                docs = PyPDFLoader(path).load()
            elif fname.lower().endswith((".md", ".txt")):
                docs = TextLoader(path, encoding="utf-8").load()
            else:
                continue
            for d in docs:
                d.metadata["category"] = category
                d.metadata["source_file"] = fname
            all_docs.extend(docs)
            print(f"Loaded {fname} ({category}) - {len(docs)} pages/sections")
    return all_docs

def build_index():
    docs = load_all_documents()
    print(f"Total documents loaded: {len(docs)}")

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks")

    FASTEMBED_CACHE = os.path.join(BASE_DIR, "fastembed_cache")
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5", cache_dir=FASTEMBED_CACHE)

    
    vectordb = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory=DB_DIR,
)
    vectordb.persist()
    print(f"Index built at {DB_DIR} with categories: {CATEGORIES}")

if __name__ == "__main__":
    build_index()