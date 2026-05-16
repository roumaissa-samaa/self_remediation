import subprocess
import json
import logging
import os

logger = logging.getLogger(__name__)

_MCP_MODE = os.getenv("MCP_MODE", "mock")

# Statuses that indicate a pod is in a genuinely unhealthy waiting/terminated state
_UNHEALTHY_WAITING = {
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
    "OOMKilled", "Error", "CreateContainerError", "InvalidImageName",
}
_UNHEALTHY_TERMINATED = {"OOMKilled", "Error", "Evicted"}


def is_pod_unhealthy(service: str, namespace: str) -> bool:

    if _MCP_MODE != "real":
        return True

    try:
        r = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            logger.warning("pre_check: kubectl failed (%s) — allowing through", r.stderr[:150])
            return True

        data = json.loads(r.stdout)
        for item in data.get("items", []):
            pod_name = item["metadata"]["name"]
            # Match by exact name or prefix (service might be full pod name)
            if pod_name != service and not pod_name.startswith(service):
                continue

            container_statuses = item.get("status", {}).get("containerStatuses", [])
            for cs in container_statuses:
                waiting_reason = cs.get("state", {}).get("waiting", {}).get("reason", "")
                if waiting_reason in _UNHEALTHY_WAITING:
                    logger.debug("pre_check: %s is unhealthy (waiting: %s)", pod_name, waiting_reason)
                    return True
                last_reason = cs.get("lastState", {}).get("terminated", {}).get("reason", "")
                if last_reason in _UNHEALTHY_TERMINATED:
                    logger.debug("pre_check: %s is unhealthy (last terminated: %s)", pod_name, last_reason)
                    return True

            # High restart count is also a sign of instability
            restarts = sum(cs.get("restartCount", 0) for cs in container_statuses)
            if restarts > 0:
                logger.debug("pre_check: %s has %d restarts", pod_name, restarts)
                return True

        logger.info("pre_check: no unhealthy pod found matching service=%s — skipping", service)
        return False

    except Exception as exc:
        logger.warning("pre_check: error (%s) — allowing through", exc)
        return True
