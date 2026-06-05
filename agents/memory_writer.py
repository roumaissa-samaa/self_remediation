from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from langchain_ollama import OllamaEmbeddings
from orchestrator.state import AgentState
from config.logger import get_logger
from config.circuit_breaker import get_breaker
import os, uuid
from dotenv import load_dotenv

load_dotenv(override=True)

log = get_logger("agent.memory")

client     = QdrantClient(url=os.getenv("QDRANT_URL"))
embeddings = OllamaEmbeddings(model=os.getenv("OLLAMA_EMBED_MODEL"))
_cb        = get_breaker("qdrant")


def enrich_memory(state: AgentState) -> AgentState:
    inc     = state["incident"]
    obs     = state["obs"]
    comm    = state["comm"]
    exec_st = state["execution"]
    opa_st  = state.get("opa", {})

    plan = exec_st.get("remediation_plan") or []
    if isinstance(plan, dict):
        plan = [plan]

    actions_summary = "; ".join(
        f"{a.get('action', '')}:{a.get('target', '')}" for a in plan
    )
    text = (
        f"Incident: {inc['alertname']}. "
        f"Service: {inc['service']}. "
        f"Cause: {obs['incident_cause']}. "
        f"Actions: {actions_summary}"
    )

    try:
        vector = _cb.call(embeddings.embed_query, text)
    except Exception as e:
        log.warning("memory enrichment skipped — Qdrant unavailable", extra={"error": str(e)})
        return {**state}

    memory_point = PointStruct(
        id=inc["incident_id"],
        vector=vector,
        payload={
            "incident":   inc["alertname"],
            "service":    inc["service"],
            "causes":     obs["incident_cause"],
            "remediation": plan,
            "agent":      comm["active_agent"],
            "type":       obs.get("incident_type", ""),
            "resolved":   exec_st["resolved"],
            "opa_reason": opa_st.get("reason", ""),
        },
    )

    try:
        _cb.call(client.upsert, collection_name="memory", points=[memory_point])
        log.info("memory enriched", extra={
            "incident_id": inc["incident_id"],
            "resolved":    exec_st["resolved"],
        })
    except Exception as e:
        log.warning("memory upsert skipped — Qdrant unavailable", extra={"error": str(e)})

    return {**state}


def write_to_cache(state: AgentState) -> None:
    inc     = state["incident"]
    obs     = state["obs"]
    comm    = state["comm"]
    exec_st = state["execution"]

    plan = exec_st.get("remediation_plan") or []
    if isinstance(plan, dict):
        plan = [plan]

    actions_summary = "; ".join(
        f"{a.get('action', '')}:{a.get('target', '')}" for a in plan
    )
    text = (
        f"Incident: {inc['alertname']}. "
        f"Service: {inc['service']}. "
        f"Cause: {obs['incident_cause']}. "
        f"Actions: {actions_summary}"
    )
    try:
        vector = _cb.call(embeddings.embed_query, text)
        existing = _cb.call(
            client.query_points,
            collection_name="semantic_cache",
            query=vector,
            limit=1,
        ).points
    except Exception as e:
        log.warning("semantic cache write skipped — Qdrant unavailable", extra={"error": str(e)})
        return

    if existing and existing[0].score > 0.90:
        log.info("already in semantic cache — skip", extra={"score": round(existing[0].score, 2)})
        return

    cache_point = PointStruct(
        id=str(uuid.uuid4()),
        vector=vector,
        payload={
            "incident":    inc["alertname"],
            "service":     inc["service"],
            "causes":      obs["incident_cause"],
            "remediation": plan,
            "agent":       comm["active_agent"],
            "type":        obs.get("incident_type", ""),
        },
    )
    try:
        _cb.call(client.upsert, collection_name="semantic_cache", points=[cache_point])
        log.info("semantic cache enriched", extra={"incident_id": inc["incident_id"]})
    except Exception as e:
        log.warning("semantic cache upsert skipped — Qdrant unavailable", extra={"error": str(e)})
