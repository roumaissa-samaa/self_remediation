import requests
from elasticsearch import Elasticsearch
from orchestrator.state import AgentState
from config.logger import get_logger
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

log = get_logger("agent.notifier")
es  = Elasticsearch(os.getenv("ELASTICSEARCH_URL"))

_TEAMS_CRITICAL = os.getenv("TEAMS_WEBHOOK_CRITICAL")
_TEAMS_RESOLVED = os.getenv("TEAMS_WEBHOOK_RESOLVED")


def _adaptive_card(body: list) -> dict:
    return {
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl":  None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type":    "AdaptiveCard",
                    "version": "1.4",
                    "body":    body,
                },
            }
        ]
    }


def _fact(title: str, value: str) -> dict:
    return {"title": title, "value": str(value)}


def _post_teams(url: str, payload: dict) -> None:
    if not url:
        log.warning("Teams webhook URL not configured — notification skipped")
        return
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        log.info("Teams notification sent", extra={"status": r.status_code})
    except Exception as e:
        log.error("Teams webhook error", extra={"error": str(e)})


def notify_operator(state: AgentState) -> AgentState:
    inc     = state["incident"]
    obs     = state["obs"]
    comm    = state["comm"]
    opa_st  = state["opa"]
    exec_st = state["execution"]
    ts      = datetime.now(timezone.utc).isoformat()

    message = {
        "type":           "DEFINITIVE_BLOCK",
        "incident_id":    inc["incident_id"],
        "alertname":      inc["alertname"],
        "service":        inc["service"],
        "namespace":      inc["namespace"],
        "incident_cause": obs["incident_cause"],
        "agent":          comm["active_agent"],
        "plan_refuse":    exec_st["remediation_plan"],
        "opa_reason":     opa_st["reason"],
        "retry_count":    opa_st["retry_count"],
        "manual_action":  "Human intervention required",
        "timestamp":      ts,
    }

    log.warning("definitive block — operator intervention required", extra={
        "incident_id": inc["incident_id"],
        "service":     inc["service"],
        "cause":       obs["incident_cause"],
        "opa_reason":  opa_st["reason"],
        "retry_count": opa_st["retry_count"],
    })

    def _plan_lines(plan: list) -> str:
        return "\n".join(f"• {a.get('command', a)}" for a in plan) if plan else "N/A"

    initial_plan = exec_st.get("initial_plan") or exec_st.get("remediation_plan") or []

    card = _adaptive_card([
        {
            "type":   "TextBlock",
            "size":   "Large",
            "weight": "Bolder",
            "color":  "Attention",
            "text":   f" BLOCKED — {inc['alertname']}",
            "wrap":   True,
        },
        {
            "type":  "FactSet",
            "facts": [
                _fact("Incident ID",  inc["incident_id"]),
                _fact("Alert",        inc["alertname"]),
                _fact("Service",      inc["service"]),
                _fact("Namespace",    inc["namespace"]),
                _fact("Agent",        comm["active_agent"]),
                _fact("Retries",      opa_st["retry_count"]),
                _fact("OPA reason",   opa_st["reason"]),
                _fact("Cause",        obs["incident_cause"][:300]),
                _fact("Action",       "Human intervention required"),
                _fact("Timestamp",    ts),
            ],
        },
        {
            "type": "TextBlock",
            "text": f"**Initial plan (rejected by OPA):**\n{_plan_lines(initial_plan)}",
            "wrap": True,
        },
    ])

    _post_teams(_TEAMS_CRITICAL, card)

    try:
        es.index(index="audit_trail", id=inc["incident_id"], document=message)
        log.info("block recorded in ELK", extra={"incident_id": inc["incident_id"]})
    except Exception as e:
        log.error("ELK block record error", extra={"error": str(e)})

    return {
        **state,
        "opa":       {**opa_st, "blocked": True},
        "execution": {**exec_st, "resolved": False},
    }


def notify_unresolved(
    incident_id: str,
    service: str,
    namespace: str,
    cause: str,
    error_detail: str,
    plan: list | None = None,
    exec_results: list | None = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    log.warning("execution failed — operator intervention required", extra={
        "incident_id": incident_id,
        "service":     service,
        "error":       error_detail,
    })

    plan         = plan or []
    exec_results = exec_results or []
    action_lines = []
    for i, action in enumerate(plan):
        cmd    = action.get("command", str(action))
        result = exec_results[i] if i < len(exec_results) else {}
        status = result.get("status", "unknown")
        detail = result.get("detail", "")
        icon   = "ok" if status == "success" else "No"
        line   = f"{icon} {cmd}"
        if status != "success" and detail:
            line += f"\n   └ {detail[:200]}"
        action_lines.append(line)

    actions_text = "\n".join(action_lines) if action_lines else "N/A"

    card = _adaptive_card([
        {
            "type":   "TextBlock",
            "size":   "Large",
            "weight": "Bolder",
            "color":  "Attention",
            "text":   f"UNRESOLVED — {service}",
            "wrap":   True,
        },
        {
            "type":  "FactSet",
            "facts": [
                _fact("Incident ID",  incident_id),
                _fact("Service",      service),
                _fact("Namespace",    namespace),
                _fact("Cause",        cause[:300]),
                _fact("Error",        error_detail[:300]),
                _fact("Action",       "Human intervention required"),
                _fact("Timestamp",    ts),
            ],
        },
        {
            "type": "TextBlock",
            "text": f"**OPA-validated plan — result per action:**\n{actions_text}",
            "wrap": True,
        },
    ])

    _post_teams(_TEAMS_CRITICAL, card)


def notify_resolved(
    incident_id: str,
    service: str,
    namespace: str,
    cause: str,
    actions: list,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    log.info("incident resolved — notifying Teams", extra={
        "incident_id": incident_id,
        "service":     service,
    })

    actions_text = "\n".join(f"• {a.get('command', a)}" for a in actions) if actions else "N/A"

    card = _adaptive_card([
        {
            "type":   "TextBlock",
            "size":   "Large",
            "weight": "Bolder",
            "color":  "Good",
            "text":   f"RESOLVED — {service}",
            "wrap":   True,
        },
        {
            "type":  "FactSet",
            "facts": [
                _fact("Incident ID", incident_id),
                _fact("Service",     service),
                _fact("Namespace",   namespace),
                _fact("Cause",       cause[:300]),
                _fact("Timestamp",   ts),
            ],
        },
        {
            "type": "TextBlock",
            "text": f"**Actions applied:**\n{actions_text}",
            "wrap": True,
        },
    ])

    _post_teams(_TEAMS_RESOLVED, card)


def notify_resolved_node(state: AgentState) -> AgentState:
    from agents.memory_writer import write_to_cache
    inc     = state["incident"]
    obs     = state["obs"]
    exec_st = state["execution"]

    notify_resolved(
        incident_id=inc["incident_id"],
        service=inc["service"],
        namespace=inc["namespace"],
        cause=obs["incident_cause"],
        actions=exec_st.get("remediation_plan", []),
    )
    write_to_cache(state)

    return {
        **state,
        "execution": {**exec_st, "post_check_confirmed": True, "resolved": True},
    }


def notify_unresolved_node(state: AgentState) -> AgentState:
    inc     = state["incident"]
    obs     = state["obs"]
    exec_st = state["execution"]

    exec_error   = exec_st.get("exec_error", "")
    error_detail = exec_error if exec_error else "post-check: pod still not healthy after remediation"

    notify_unresolved(
        incident_id=inc["incident_id"],
        service=inc["service"],
        namespace=inc["namespace"],
        cause=obs["incident_cause"],
        error_detail=error_detail,
        plan=exec_st.get("remediation_plan", []),
        exec_results=exec_st.get("execution_result") if isinstance(exec_st.get("execution_result"), list) else [],
    )

    return {
        **state,
        "execution": {**exec_st, "post_check_confirmed": False, "resolved": False},
    }