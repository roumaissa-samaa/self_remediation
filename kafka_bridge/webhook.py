from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import os
import uuid
import time
import logging
from datetime import datetime
from kafka_bridge.producer import publish_incident
from kafka_bridge.pre_check import is_pod_unhealthy

logger = logging.getLogger(__name__)

_ALLOWED_NAMESPACE = os.getenv("K8S_NAMESPACE", "default")
# Suppress duplicate publishes for the same pod within this window (blocks OR-branch floods
# and Alertmanager repeat_interval resends)
_DEDUP_TTL = float(os.getenv("WEBHOOK_DEDUP_TTL_S", "60"))

app = FastAPI()

# service:namespace → last published timestamp
_recent_publishes: dict[str, float] = {}


class Alert(BaseModel):
    alertname: str
    service: str
    namespace: str
    message: str
    source: Optional[str] = "alertmanager"


def _deployment_name(service: str) -> str:
    parts = service.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-2])
    return service


def _dedup_key(service: str, namespace: str) -> str:
    return f"{_deployment_name(service)}:{namespace}"


def _is_dedup_blocked(service: str, namespace: str) -> bool:
    key = _dedup_key(service, namespace)
    now = time.time()
    last = _recent_publishes.get(key)
    if last is not None and (now - last) < _DEDUP_TTL:
        logger.info(
            "Webhook dedup: skipping %s (published %.0fs ago, window=%gs)",
            key, now - last, _DEDUP_TTL,
        )
        return True
    return False


def _publish(alertname: str, service: str, namespace: str, message: str, source: str) -> str:
    incident_id = str(uuid.uuid4())
    publish_incident({
        "incident_id": incident_id,
        "alertname":   alertname,
        "service":     service,
        "namespace":   namespace,
        "message":     message,
        "source":      source,
        "timestamp":   datetime.utcnow().isoformat(),
    })
    _recent_publishes[_dedup_key(service, namespace)] = time.time()
    return incident_id


@app.post("/alert")
async def receive_alert(request: Request):
    try:
        body = await request.json()

        # Alertmanager native format: {"alerts": [...], "receiver": ..., ...}
        if "alerts" in body:
            incident_ids = []
            for alert in body.get("alerts", []):
                if alert.get("status") != "firing":
                    continue
                labels      = alert.get("labels", {})
                annotations = alert.get("annotations", {})

                alertname = annotations.get("alertname") or labels.get("alertname", "unknown")

                raw_service = annotations.get("service") or labels.get("pod") or labels.get("service", "unknown")
                service     = _deployment_name(raw_service)
                namespace = annotations.get("namespace") or labels.get("namespace", "default")
                message   = (annotations.get("message")
                            or annotations.get("summary")
                            or annotations.get("description", ""))

                if namespace != _ALLOWED_NAMESPACE:
                    continue

                if _is_dedup_blocked(service, namespace):
                    continue

                if not is_pod_unhealthy(service, namespace):
                    logger.info("pre_check: %s/%s appears healthy — skipping", namespace, service)
                    continue

                incident_ids.append(_publish(alertname, service, namespace, message, "alertmanager"))

            return {"status": "received", "incident_ids": incident_ids}

        # Simple flat format: used by simulate_alert.py and manual curl — no namespace filter
        alert = Alert(**body)

        if _is_dedup_blocked(alert.service, alert.namespace):
            return {"status": "skipped", "reason": "dedup_window"}

        if not is_pod_unhealthy(alert.service, alert.namespace):
            logger.info("pre_check: %s/%s appears healthy — skipping", alert.namespace, alert.service)
            return {"status": "skipped", "reason": "pod_healthy"}

        incident_id = _publish(alert.alertname, alert.service, alert.namespace, alert.message, alert.source)
        return {"status": "received", "incident_id": incident_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok"}
