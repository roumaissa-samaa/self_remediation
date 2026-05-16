from elasticsearch import Elasticsearch
from orchestrator.state import AgentState
from config.logger import get_logger
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

log = get_logger("agent.notifier")
es  = Elasticsearch(os.getenv("ELASTICSEARCH_URL"))


def notify_operator(state: AgentState) -> AgentState:
    inc     = state["incident"]
    obs     = state["obs"]
    comm    = state["comm"]
    opa_st  = state["opa"]
    exec_st = state["execution"]

    message = {
        "type":            "DEFINITIVE_BLOCK",
        "incident_id":     inc["incident_id"],
        "alertname":       inc["alertname"],
        "service":         inc["service"],
        "namespace":       inc["namespace"],
        "incident_cause":  obs["incident_cause"],
        "agent":           comm["active_agent"],
        "plan_refuse":     exec_st["remediation_plan"],
        "opa_reason":      opa_st["reason"],
        "retry_count":     opa_st["retry_count"],
        "manual_action":   "Human intervention required",
        "timestamp":       datetime.utcnow().isoformat(),
    }

    log.warning("definitive block — operator intervention required", extra={
        "incident_id": inc["incident_id"],
        "service":     inc["service"],
        "cause":       obs["incident_cause"],
        "opa_reason":  opa_st["reason"],
        "retry_count": opa_st["retry_count"],
    })

    try:
        es.index(index="audit_trail", document=message)
        log.info("block recorded in ELK", extra={"incident_id": inc["incident_id"]})
    except Exception as e:
        log.error("ELK block record error", extra={"error": str(e)})

    return {
        **state,
        "execution": {**exec_st, "resolved": False},
    }
