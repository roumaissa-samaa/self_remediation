from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import os
from dotenv import load_dotenv

load_dotenv()

assert os.getenv("QDRANT_URL"), "QDRANT_URL missing from environment variables"

print("WARNING: this operation will delete and recreate all Qdrant collections.")
print("All data (memory, RAG, cache) will be erased.")
confirm = input("Type 'YES' to confirm: ")
if confirm != "YES":
    print("Cancelled.")
    exit(0)

client = QdrantClient(url=os.getenv("QDRANT_URL"))

collections = [
    ("memory",         "Incident history and agent memory"),
    ("documents",      "RAG knowledge base"),
    ("semantic_cache", "LLM semantic response cache"),
]

for name, description in collections:
    client.recreate_collection(
        collection_name=name,
        vectors_config=VectorParams(
            size=768,
            distance=Distance.COSINE
        )
    )
    print(f"Collection '{name}' created — {description}")

print("\n All Qdrant collections are ready!")