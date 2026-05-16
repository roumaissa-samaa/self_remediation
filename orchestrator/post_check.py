import subprocess
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_MCP_MODE         = os.getenv("MCP_MODE", "mock")
_POST_CHECK_DELAY = int(os.getenv("POST_CHECK_DELAY_S", "30"))

_UNHEALTHY_WAITING = {
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
    "OOMKilled", "Error", "CreateContainerError", "InvalidImageName",
}


def _deployment_name(service: str) -> str:
    parts = service.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-2])
    return service


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
