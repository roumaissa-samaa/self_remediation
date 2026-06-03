from elasticsearch import Elasticsearch
from orchestrator.state import AgentState
from config.logger import get_logger
from datetime import datetime, timezone
import os
import requests
from dotenv import load_dotenv

load_dotenv()

log = get_logger("agent.notifier")
es  = Elasticsearch(os.getenv("ELASTICSEARCH_URL"))


def _adaptive_card(title: str, color: str, facts: list[dict]) -> dict:
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": title,
                            "weight": "Bolder",
                            "size": "Large",
                            "color": color,
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": facts,
                        },
                    ],
                },
            }
        ],
    }


def _post_teams(webhook_url: str, payload: dict, incident_id: str) -> None:
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Teams notification sent", extra={"incident_id": incident_id, "status": resp.status_code})
    except Exception as e:
        log.error("Teams notification failed", extra={"incident_id": incident_id, "error": str(e)})


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

    webhook_url = os.getenv("TEAMS_WEBHOOK_CRITICAL")
    if webhook_url:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        plan = exec_st.get("remediation_plan") or []
        payload = _adaptive_card(
            title="🚨 OPA BLOCK — Intervention requise",
            color="Attention",
            facts=[
                {"title": "Incident ID",  "value": inc["incident_id"]},
                {"title": "Alerte",       "value": inc["alertname"]},
                {"title": "Service",      "value": inc["service"]},
                {"title": "Namespace",    "value": inc["namespace"]},
                {"title": "Agent",        "value": comm["active_agent"]},
                {"title": "Actions",      "value": f"0/{len(plan)} — bloqué par OPA"},
                {"title": "Raison OPA",   "value": opa_st.get("reason", "Max retries exceeded")},
                {"title": "Post-check",   "value": "N/A — OPA bloqué"},
                {"title": "Timestamp",    "value": timestamp},
            ],
        )
        _post_teams(webhook_url, payload, inc["incident_id"])

    return {
        **state,
        "execution": {**exec_st, "resolved": False},
    }


def notify_teams_resolved(
    incident_id: str,
    alertname: str,
    service: str,
    namespace: str,
    agent: str,
    n_ok: int,
    n_total: int,
) -> None:
    webhook_url = os.getenv("TEAMS_WEBHOOK_RESOLVED")
    if not webhook_url:
        log.warning("TEAMS_WEBHOOK_RESOLVED not set — skipping")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = _adaptive_card(
        title="INCIDENT RÉSOLU",
        color="Good",
        facts=[
            {"title": "Incident ID",  "value": incident_id},
            {"title": "Alerte",       "value": alertname},
            {"title": "Service",      "value": service},
            {"title": "Namespace",    "value": namespace},
            {"title": "Agent",        "value": agent},
            {"title": "Actions",      "value": f"{n_ok}/{n_total} réussies"},
            {"title": "Post-check",   "value": "PASSED — déploiement sain"},
            {"title": "Timestamp",    "value": timestamp},
        ],
    )
    _post_teams(webhook_url, payload, incident_id)


def notify_teams_critical(
    incident_id: str,
    alertname: str,
    service: str,
    namespace: str,
    agent: str,
    n_ok: int,
    n_total: int,
    reason: str,
) -> None:
    webhook_url = os.getenv("TEAMS_WEBHOOK_CRITICAL")
    if not webhook_url:
        log.warning("TEAMS_WEBHOOK_CRITICAL not set — skipping")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = _adaptive_card(
        title="INCIDENT NON RÉSOLU",
        color="Attention",
        facts=[
            {"title": "Incident ID",  "value": incident_id},
            {"title": "Alerte",       "value": alertname},
            {"title": "Service",      "value": service},
            {"title": "Namespace",    "value": namespace},
            {"title": "Agent",        "value": agent},
            {"title": "Actions",      "value": f"{n_ok}/{n_total} exécutées"},
            {"title": "Post-check",   "value": f"FAILED — {reason}"},
            {"title": "Timestamp",    "value": timestamp},
        ],
    )
    _post_teams(webhook_url, payload, incident_id)
