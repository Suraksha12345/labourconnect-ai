import os
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
BASE_DIR = os.path.dirname(__file__)
FASTEMBED_CACHE = os.path.join(BASE_DIR, "fastembed_cache")

from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma

DB_DIR = os.path.join(BASE_DIR, "chroma_db")
_vectordb = None

def _get_db():
    global _vectordb
    if _vectordb is None:
        embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5", cache_dir=FASTEMBED_CACHE)
        _vectordb = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)
    return _vectordb

def search_knowledge_base(query: str, k: int = 3, category: str = None) -> str:
    db = _get_db()
    filter_dict = {"category": category} if category else None
    results = db.similarity_search(query, k=k, filter=filter_dict)
    if not results:
        return "No relevant information found in knowledge base."
    return "\n\n---\n\n".join(
        f"[{r.metadata.get('category', 'general')} - {r.metadata.get('source_file', '')}]\n{r.page_content}"
        for r in results
    )