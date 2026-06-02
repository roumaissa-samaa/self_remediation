import os
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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
                            "size": "Large",
                            "weight": "Bolder",
                            "color": color,
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": f["name"], "value": str(f["value"])}
                                for f in facts
                            ],
                        },
                    ],
                },
            }
        ],
    }


def _post(payload: dict, url_env: str = "TEAMS_WEBHOOK_CRITICAL") -> None:
    url = os.getenv(url_env, "")
    if not url:
        logger.warning("%s not set — Teams notification skipped", url_env)
        return
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Teams notification sent to %s (status %d)", url_env, r.status_code)
    except Exception as exc:
        logger.error("Teams notification failed (%s): %s", url_env, exc)


def notify_teams_resolved(incident: dict, agent: str, n_ok: int, n_total: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    facts = [
        {"name": "Incident ID",  "value": incident.get("incident_id", "—")},
        {"name": "Alert",        "value": incident.get("alertname",   "—")},
        {"name": "Service",      "value": incident.get("service",     "—")},
        {"name": "Namespace",    "value": incident.get("namespace",   "—")},
        {"name": "Agent",        "value": agent},
        {"name": "Actions",      "value": f"{n_ok}/{n_total} successful"},
        {"name": "Post-check",   "value": "PASSED — deployment healthy"},
        {"name": "Timestamp",    "value": now},
    ]
    _post(_adaptive_card(" Incident Resolved", "Good", facts), url_env="TEAMS_WEBHOOK_RESOLVED")


def notify_teams_unresolved(
    incident: dict,
    final_state: dict,
    agent: str,
    n_ok: int,
    n_total: int,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    obs     = final_state.get("obs",       {})
    opa_st  = final_state.get("opa",       {})
    exec_st = final_state.get("execution", {})

    execution_results = exec_st.get("execution_result") or []
    failed_actions = [
        r.get("action", "?") for r in execution_results if r.get("status") != "success"
    ]

    facts = [
        {"name": "Incident ID",       "value": incident.get("incident_id",          "—")},
        {"name": "Alert",             "value": incident.get("alertname",             "—")},
        {"name": "Service",           "value": incident.get("service",               "—")},
        {"name": "Namespace",         "value": incident.get("namespace",             "—")},
        {"name": "Agent",             "value": agent},
        {"name": "Incident type",     "value": obs.get("incident_type",             "—")},
        {"name": "Root cause",        "value": obs.get("incident_cause",            "—")},
        {"name": "Hypothesis",        "value": obs.get("root_cause_hypothesis",     "—")},
        {"name": "Affected",          "value": ", ".join(obs.get("affected_components", [])) or "—"},
        {"name": "Actions attempted", "value": f"{n_ok}/{n_total} successful"},
        {"name": "Failed actions",    "value": ", ".join(failed_actions) if failed_actions else "none"},
        {"name": "OPA approved",      "value": str(opa_st.get("approved",  "—"))},
        {"name": "OPA reason",        "value": opa_st.get("reason",        "—")},
        {"name": "OPA retries",       "value": str(opa_st.get("retry_count", 0))},
        {"name": "Post-check",        "value": "FAILED — deployment not healthy"},
        {"name": "Action required",   "value": "Manual intervention needed"},
        {"name": "Timestamp",         "value": now},
    ]
    _post(_adaptive_card(" Incident NOT Resolved — Manual Action Required", "Attention", facts), url_env="TEAMS_WEBHOOK_CRITICAL")


def notify_teams_opa_blocked(
    incident: dict,
    obs: dict,
    opa_st: dict,
    agent: str,
    plan: list,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    facts = [
        {"name": "Incident ID",     "value": incident.get("incident_id",        "—")},
        {"name": "Alert",           "value": incident.get("alertname",           "—")},
        {"name": "Service",         "value": incident.get("service",             "—")},
        {"name": "Namespace",       "value": incident.get("namespace",           "—")},
        {"name": "Agent",           "value": agent},
        {"name": "Incident type",   "value": obs.get("incident_type",           "—")},
        {"name": "Root cause",      "value": obs.get("incident_cause",          "—")},
        {"name": "Hypothesis",      "value": obs.get("root_cause_hypothesis",   "—")},
        {"name": "Affected",        "value": ", ".join(obs.get("affected_components", [])) or "—"},
        {"name": "Plan refused",    "value": ", ".join(str(a) for a in plan) if plan else "—"},
        {"name": "OPA reason",      "value": opa_st.get("reason",              "—")},
        {"name": "OPA retries",     "value": str(opa_st.get("retry_count", 0))},
        {"name": "Action required", "value": "Manual intervention needed"},
        {"name": "Timestamp",       "value": now},
    ]
    _post(_adaptive_card(" OPA Definitive Block — Manual Action Required", "Attention", facts), url_env="TEAMS_WEBHOOK_CRITICAL")
