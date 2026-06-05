from elasticsearch import Elasticsearch
from orchestrator.state import AgentState
from config.logger import get_logger
from config.circuit_breaker import get_breaker
from datetime import datetime
import os, json
from dotenv import load_dotenv

load_dotenv()

log = get_logger("agent.audit")
es  = Elasticsearch(os.getenv("ELASTICSEARCH_URL"))
_cb = get_breaker("elasticsearch", failure_threshold=3, recovery_timeout=30.0)


def record_audit(state: AgentState) -> AgentState:
    inc    = state["incident"]
    obs    = state["obs"]
    comm   = state["comm"]
    opa_st = state["opa"]
    exec_st = state["execution"]

    doc = {
        "incident_id":      inc["incident_id"],
        "alertname":        inc["alertname"],
        "service":          inc["service"],
        "namespace":        inc["namespace"],
        "incident_type":    obs["incident_type"],
        "incident_cause":   obs["incident_cause"],
        "active_agent":     comm["active_agent"],
        "remediation_plan": json.dumps(exec_st["remediation_plan"]),
        "opa_approved":     opa_st["approved"],
        "opa_reason":       opa_st["reason"],
        "retry_count":      opa_st["retry_count"],
        "execution_result": json.dumps(exec_st["execution_result"]),
        "resolved":         exec_st.get("post_check_confirmed", False),
        "timestamp":        datetime.utcnow().isoformat(),
    }

    try:
        _cb.call(es.index, index="audit_trail", id=inc["incident_id"], document=doc)
        log.info("audit recorded", extra={"incident_id": inc["incident_id"]})
    except Exception as e:
        log.warning("audit skipped — Elasticsearch unavailable", extra={"error": str(e)})

    return {**state}

