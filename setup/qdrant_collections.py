from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import os
from dotenv import load_dotenv

load_dotenv()

assert os.getenv("QDRANT_URL"), "QDRANT_URL manquante dans les variables d'environnement"

print("ATTENTION : cette opération va supprimer et recréer toutes les collections Qdrant.")
print("Toutes les données (mémoire, RAG, cache) seront effacées.")
confirm = input("Taper 'OUI' pour confirmer : ")
if confirm != "OUI":
    print("Annulé.")
    exit(0)

client = QdrantClient(url=os.getenv("QDRANT_URL"))

collections = [
    ("memory",         "Historique incidents et mémoire agents"),
    ("documents",      "Base de connaissance RAG documentaire"),
    ("semantic_cache", "Cache sémantique des réponses LLM"),
]

for name, description in collections:
    client.recreate_collection(
        collection_name=name,
        vectors_config=VectorParams(
            size=768,
            distance=Distance.COSINE
        )
    )
    print(f"Collection '{name}' créée — {description}")

print("\n Toutes les collections Qdrant sont prêtes !")