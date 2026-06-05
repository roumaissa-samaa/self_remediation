import os
import requests
import subprocess
from config.logger import get_logger

log = get_logger("mcp.prometheus")

_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
_NAMESPACE      = os.getenv("K8S_NAMESPACE", "default")


def get_logs(source: str = "platform") -> list:
    logs      = []
    namespace = _NAMESPACE

    # Recent warning events
    try:
        r = subprocess.run(
            ["kubectl", "get", "events", "-n", namespace,
            "--sort-by=.lastTimestamp", "--field-selector=type=Warning", "--no-headers"],
            capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.strip().splitlines()[-15:]:
            if line.strip():
                logs.append(f"EVENT: {line.strip()}")
    except Exception as e:
        log.warning("kubectl events error", extra={"error": str(e)})

    # Pod logs (current + previous if crashed)
    try:
        pods_r = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "--no-headers",
            "-o", "custom-columns=NAME:.metadata.name"],
            capture_output=True, text=True, timeout=10,
        )
        pod_names = [p.strip() for p in pods_r.stdout.splitlines() if p.strip()]

        for pod in pod_names[:6]:
            for flags in (["--tail=10", "--previous"], ["--tail=10"]):
                r = subprocess.run(
                    ["kubectl", "logs", pod, "-n", namespace] + flags,
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0 and r.stdout.strip():
                    for line in r.stdout.strip().splitlines()[-5:]:
                        logs.append(f"{pod}: {line.strip()}")
                    break
    except Exception as e:
        log.warning("kubectl logs error", extra={"error": str(e)})

    return logs or ["No logs available"]


def get_metrics(source: str = "platform") -> dict:
    namespace = _NAMESPACE
    metrics   = {}

    queries = {
        "restart_count":   f'kube_pod_container_status_restarts_total{{namespace="{namespace}"}}',
        "crashloop_pods":  f'kube_pod_container_status_waiting_reason{{reason="CrashLoopBackOff",namespace="{namespace}"}}',
        "oomkilled_pods":  f'kube_pod_container_status_last_terminated_reason{{reason="OOMKilled",namespace="{namespace}"}}',
        "cpu_usage_cores": f'rate(container_cpu_usage_seconds_total{{namespace="{namespace}",container!=""}}[2m])',
        "memory_bytes":    f'container_memory_working_set_bytes{{namespace="{namespace}",container!=""}}',
    }

    for name, query in queries.items():
        try:
            resp = requests.get(
                f"{_PROMETHEUS_URL}/api/v1/query",
                params={"query": query},
                timeout=5,
            )
            if resp.ok:
                results = resp.json().get("data", {}).get("result", [])
                metrics[name] = {
                    r["metric"].get("pod", r["metric"].get("container", "?")): float(r["value"][1])
                    for r in results if r.get("value")
                }
        except Exception as e:
            log.warning("prometheus query error", extra={"metric": name, "error": str(e)})
            metrics[name] = {}

    return metrics


def get_pod_memory_peak(service: str, namespace: str) -> dict:
    """Peak memory usage (working set) for pods matching the service.

    Tries max_over_time[1h] first. Falls back to an instant query because
    OOMKilled pods often run too briefly for Prometheus to accumulate 1h of data.
    """
    selector = f'namespace="{namespace}",pod=~"{service}-[a-z0-9]+-[a-z0-9]+"'

    def _query_peak(promql: str, window: str) -> dict:
        resp = requests.get(
            f"{_PROMETHEUS_URL}/api/v1/query",
            params={"query": promql},
            timeout=5,
        )
        if not resp.ok:
            return {}
        results = resp.json().get("data", {}).get("result", [])
        if not results:
            return {}
        peak_bytes = max(float(r["value"][1]) for r in results if r.get("value"))
        return {
            "peak_memory_bytes": peak_bytes,
            "peak_memory_human": f"{peak_bytes / (1024 * 1024):.0f}Mi",
            "window": window,
        }

    try:
        result = _query_peak(
            f'max_over_time(container_memory_working_set_bytes{{{selector}}}[1h])', "1h"
        )
        if result:
            return result

        # Fallback: instant query — pod may be running between CrashLoop restarts
        result = _query_peak(
            f'container_memory_working_set_bytes{{{selector}}}', "instant"
        )
        if result:
            log.info("prometheus peak memory: using instant fallback", extra={"service": service})
            return result

        log.warning("prometheus peak memory: no data", extra={"service": service, "namespace": namespace})
    except Exception as e:
        log.warning("prometheus peak memory error", extra={"service": service, "error": str(e)})
    return {}
