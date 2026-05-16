from elasticsearch import Elasticsearch
from orchestrator.state import AgentState
from config.logger import get_logger
from datetime import datetime
import os, json
from dotenv import load_dotenv

load_dotenv()

log = get_logger("agent.audit")
es  = Elasticsearch(os.getenv("ELASTICSEARCH_URL"))


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
        "resolved":         False,
        "timestamp":        datetime.utcnow().isoformat(),
    }

    try:
        es.index(index="audit_trail", id=inc["incident_id"], document=doc)
        log.info("audit recorded", extra={"incident_id": inc["incident_id"]})
    except Exception as e:
        log.error("audit ELK error", extra={"error": str(e)})

    return {**state}


def update_audit_resolved(incident_id: str, confirmed: bool) -> None:
    try:
        es.update(
            index="audit_trail",
            id=incident_id,
            body={"doc": {"resolved": confirmed}},
        )
        log.info("audit resolved updated", extra={"incident_id": incident_id, "resolved": confirmed})
    except Exception as e:
        log.error("audit update ELK error", extra={"error": str(e)})
