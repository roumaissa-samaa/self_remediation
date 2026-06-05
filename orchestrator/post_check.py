import re
import subprocess
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from orchestrator.state import AgentState

logger = logging.getLogger(__name__)

_MCP_MODE         = os.getenv("MCP_MODE", "mock")
_POST_CHECK_DELAY = int(os.getenv("POST_CHECK_DELAY_S", "30"))

_UNHEALTHY_WAITING = {
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
    "OOMKilled", "Error", "CreateContainerError", "CreateContainerConfigError", "InvalidImageName",
}

_UNHEALTHY_EVENT_REASONS = {
    "BackOff", "CrashLoopBackOff", "OOMKilling", "Failed",
    "FailedMount", "FailedScheduling", "Unhealthy", "CreateContainerConfigError",
}

_K8S_POD_SUFFIX = re.compile(r'-[a-z0-9]{8,10}-[a-z0-9]{5}$')


def _deployment_name(service: str) -> str:
    return _K8S_POD_SUFFIX.sub('', service)


def verify_remediation(service: str, namespace: str, incident_id: str) -> bool:
    if _MCP_MODE != "real":
        return True

    if _POST_CHECK_DELAY > 0:
        logger.info(
            "Post-check [%s]: waiting %ds before verifying remediation of %s/%s...",
            incident_id, _POST_CHECK_DELAY, namespace, service,
        )
        time.sleep(_POST_CHECK_DELAY)

    deployment = _deployment_name(service)

    try:
        r = subprocess.run(
            ["kubectl", "get", "deployment", deployment, "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            logger.warning(
                "Post-check [%s]: deployment '%s' not found — cannot verify",
                incident_id, deployment,
            )
            return False

        dep    = json.loads(r.stdout)
        spec_replicas   = dep.get("spec", {}).get("replicas", 0)
        ready_replicas  = dep.get("status", {}).get("readyReplicas", 0)
        unavailable     = dep.get("status", {}).get("unavailableReplicas", 0)

        if spec_replicas == 0:
            logger.warning(
                "Post-check [%s]: deployment '%s' scaled to 0 — incident NOT truly resolved",
                incident_id, deployment,
            )
            return False

        r2 = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace,
             "-l", f"app={deployment}", "-o", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if r2.returncode == 0:
            for item in json.loads(r2.stdout).get("items", []):
                pod_name = item["metadata"]["name"]
                for cs in item.get("status", {}).get("containerStatuses", []):
                    reason = cs.get("state", {}).get("waiting", {}).get("reason", "")
                    if reason in _UNHEALTHY_WAITING:
                        logger.warning(
                            "Post-check [%s]: pod '%s' still unhealthy (%s) — remediation FAILED",
                            incident_id, pod_name, reason,
                        )
                        return False

        if ready_replicas >= 1 and unavailable == 0:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
            if r2.returncode == 0:
                for item in json.loads(r2.stdout).get("items", []):
                    pod_name = item["metadata"]["name"]
                    ev = subprocess.run(
                        ["kubectl", "get", "events", "-n", namespace,
                         "--field-selector", f"involvedObject.name={pod_name},type=Warning",
                         "-o", "json"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if ev.returncode == 0:
                        for e in json.loads(ev.stdout).get("items", []):
                            reason = e.get("reason", "")
                            if reason not in _UNHEALTHY_EVENT_REASONS:
                                continue
                            ts_str = e.get("lastTimestamp") or e.get("eventTime", "")
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                if ts >= cutoff:
                                    logger.warning(
                                        "Post-check [%s]: pod '%s' has recent Warning event '%s' — application may not be truly healthy",
                                        incident_id, pod_name, reason,
                                    )
                            except Exception:
                                pass

            logger.info(
                "Post-check [%s]: deployment '%s' healthy (%d/%d ready) — remediation CONFIRMED",
                incident_id, deployment, ready_replicas, spec_replicas,
            )
            return True

        logger.warning(
            "Post-check [%s]: deployment '%s' not fully ready "
            "(%d/%d ready, %d unavailable) — remediation FAILED",
            incident_id, deployment, ready_replicas, spec_replicas, unavailable,
        )
        return False

    except Exception as exc:
        logger.warning("Post-check [%s]: error (%s)", incident_id, exc)
        return False


def post_check_node(state: AgentState) -> AgentState:
    inc     = state["incident"]
    exec_st = state.get("execution", {})

    confirmed = verify_remediation(
        inc.get("service", ""),
        inc.get("namespace", "default"),
        inc.get("incident_id", ""),
    )

    return {
        **state,
        "execution": {**exec_st, "post_check_confirmed": confirmed},
    }
