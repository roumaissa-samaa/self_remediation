from qdrant_client import QdrantClient
from langchain_ollama import OllamaEmbeddings
import os
from dotenv import load_dotenv

load_dotenv()

client     = QdrantClient(url=os.getenv("QDRANT_URL"))
embeddings = OllamaEmbeddings(model=os.getenv("OLLAMA_EMBED_MODEL"))

_sep = "─" * 58


def get_cache_match(query: str) -> dict:
    threshold = float(os.getenv("CACHE_SCORE_THRESHOLD", "0.80"))
    vector    = embeddings.embed_query(query)
    results   = client.query_points(
        collection_name="semantic_cache",
        query=vector,
        limit=3,
    ).points

    best = None
    for r in results:
        if r.score > threshold:
            if best is None or r.score > best.score:
                best = r

    if best:
        score = round(best.score, 2)
        print(f"\n{_sep}")
        print(f"  [CACHE] Match — score {score}  →  similar plan sent to agent")
        print(f"          Incident : {best.payload.get('incident', '?')}  |  Agent : {best.payload.get('agent', '?')}")
        print(f"{_sep}\n")
        return {**best.payload, "score": score}

    print(f"\n{_sep}")
    print(f"  [CACHE] ✗ Miss — no similar incident found")
    print(f"{_sep}\n")
    return {}


def get_runbooks(query: str, top_k: int = 3) -> list:
    query_vector = embeddings.embed_query(query)
    results      = client.query_points(
        collection_name="documents",
        query=query_vector,
        limit=top_k * 4,
    ).points

    runbooks = []
    seen     = set()
    for r in sorted(results, key=lambda x: x.score, reverse=True):
        if r.score < 0.40:
            continue
        p   = r.payload
        key = (p.get("incident", ""), p.get("cause", ""), p.get("remediation", "")[:100])
        if key in seen:
            continue
        seen.add(key)
        runbooks.append({
            "score":       round(r.score, 3),
            "incident":    p.get("incident", ""),
            "type":        p.get("type", ""),
            "agent":       p.get("agent", ""),
            "cause":       p.get("cause", ""),
            "remediation": p.get("remediation", ""),
            "actions":     p.get("actions", ""),
        })
        if len(runbooks) >= top_k:
            break
    return runbooks
