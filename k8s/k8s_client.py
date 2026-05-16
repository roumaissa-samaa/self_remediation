import os
import json
import subprocess
from config.logger import get_logger

log = get_logger("mcp.k8s")

_NAMESPACE = os.getenv("K8S_NAMESPACE", "default")


def _kubectl_json(args: list) -> dict | None:
    r = subprocess.run(
        ["kubectl"] + args + ["-o", "json"],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode == 0 and r.stdout:
        try:
            return json.loads(r.stdout)
        except Exception:
            pass
    log.warning("kubectl failed", extra={"args": args, "stderr": r.stderr[:200]})
    return None


def get_infra_state(source: str = "platform") -> dict:
    namespace = _NAMESPACE
    pods, nodes = [], []

    pod_data = _kubectl_json(["get", "pods", "-n", namespace])
    if pod_data:
        for item in pod_data.get("items", []):
            meta     = item["metadata"]
            statuses = item.get("status", {}).get("containerStatuses", [])
            restarts = sum(c.get("restartCount", 0) for c in statuses)

            phase      = item.get("status", {}).get("phase", "Unknown")
            pod_status = phase
            terminated_reason = None
            exit_code         = None
            for c in statuses:
                waiting_reason = c.get("state", {}).get("waiting", {}).get("reason")
                if waiting_reason:
                    pod_status = waiting_reason

                last = c.get("lastState", {}).get("terminated", {})
                if last.get("reason"):
                    terminated_reason = last["reason"]
                    exit_code         = last.get("exitCode")

            containers = item.get("spec", {}).get("containers", [])
            images = [c.get("image", "") for c in containers if c.get("image")]

            pod = {
                "name":      meta["name"],
                "namespace": meta.get("namespace", namespace),
                "status":    pod_status,
                "restarts":  restarts,
                "images":    images,
            }
            if terminated_reason:
                pod["terminated_reason"] = terminated_reason
            if exit_code is not None:
                pod["exit_code"] = exit_code

            pods.append(pod)

    node_data = _kubectl_json(["get", "nodes"])
    if node_data:
        for item in node_data.get("items", []):
            conditions = item.get("status", {}).get("conditions", [])
            ready      = any(c["type"] == "Ready" and c["status"] == "True" for c in conditions)
            nodes.append({
                "name":   item["metadata"]["name"],
                "status": "Ready" if ready else "NotReady",
            })

    return {"pods": pods, "nodes": nodes}


def get_platform_config(agent_type: str) -> dict:
    namespace = _NAMESPACE

    if agent_type == "platform":
        deployments = []

        # Index ReplicaSets by owner deployment for rollout history
        rs_by_deployment: dict[str, list] = {}
        rs_data = _kubectl_json(["get", "replicasets", "-n", namespace])
        if rs_data:
            for rs in rs_data.get("items", []):
                owners = rs.get("metadata", {}).get("ownerReferences", [])
                deploy_name = next(
                    (o["name"] for o in owners if o.get("kind") == "Deployment"), None
                )
                if not deploy_name:
                    continue
                revision = rs.get("metadata", {}).get("annotations", {}).get(
                    "deployment.kubernetes.io/revision"
                )
                rs_containers = (
                    rs.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
                )
                rs_images = [c.get("image", "") for c in rs_containers if c.get("image")]
                if revision and rs_images:
                    rs_by_deployment.setdefault(deploy_name, []).append({
                        "revision": int(revision),
                        "image":    rs_images[0],
                    })

        data = _kubectl_json(["get", "deployments", "-n", namespace])
        if data:
            for item in data.get("items", []):
                name       = item["metadata"]["name"]
                spec       = item.get("spec", {})
                containers = spec.get("template", {}).get("spec", {}).get("containers", [])
                history    = sorted(
                    rs_by_deployment.get(name, []), key=lambda x: x["revision"]
                )
                deployments.append({
                    "name":            name,
                    "namespace":       namespace,
                    "replicas":        spec.get("replicas", 1),
                    "image":           containers[0].get("image", "") if containers else "",
                    "rollout_history": history,
                })
        return {
            "cluster":           "minikube",
            "namespace":         namespace,
            "deployments":       deployments,
            "available_actions": [
                "restart_pod", "scale_deployment", "rollback_deployment",
                "patch_deployment", "delete_pod", "drain_node",
            ],
        }

    # integration — no Jenkins/DB in minikube example
    return {
        "jenkins_url":      os.getenv("JENKINS_URL", ""),
        "pipelines":        [],
        "db_host":          os.getenv("DB_HOST", ""),
        "available_actions": [],
    }


def get_jenkins_state() -> dict:
    return {"pipelines": []}


def get_db_state() -> dict:
    return {"databases": []}
