from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from langchain_ollama import OllamaEmbeddings
from config.circuit_breaker import get_breaker
import logging
import os
from dotenv import load_dotenv

load_dotenv()

client     = QdrantClient(url=os.getenv("QDRANT_URL"))
embeddings = OllamaEmbeddings(model=os.getenv("OLLAMA_EMBED_MODEL"))

_sep = "─" * 58
_log = logging.getLogger("agent.memory")
_cb  = get_breaker("qdrant", failure_threshold=3, recovery_timeout=30.0)


def get_cache_match(query: str, incident_type: str = "") -> dict:
    threshold = float(os.getenv("CACHE_SCORE_THRESHOLD", "0.80"))
    try:
        vector = _cb.call(embeddings.embed_query, query)

        query_filter = (
            Filter(must=[FieldCondition(key="type", match=MatchValue(value=incident_type))])
            if incident_type else None
        )

        results = _cb.call(
            client.query_points,
            collection_name="semantic_cache",
            query=vector,
            query_filter=query_filter,
            limit=3,
        ).points
    except Exception as e:
        _log.warning("cache match unavailable — skipping: %s", e)
        print(f"\n{_sep}")
        print(f"  [CACHE] ✗ Unavailable — continuing without cache")
        print(f"{_sep}\n")
        return {}

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
    try:
        query_vector = _cb.call(embeddings.embed_query, query)
        results      = _cb.call(
            client.query_points,
            collection_name="documents",
            query=query_vector,
            limit=top_k * 4,
        ).points
    except Exception as e:
        _log.warning("runbook search unavailable — skipping: %s", e)
        return []

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
