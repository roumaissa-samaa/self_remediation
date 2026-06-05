import json
from mcp.server.fastmcp import FastMCP

server = FastMCP("k8s-mcp-server")


@server.tool()
def get_logs(source: str = "platform") -> str:
    from k8s.prometheus_client import get_logs as _fn
    return json.dumps(_fn(source))


@server.tool()
def get_metrics(source: str = "platform") -> str:
    from k8s.prometheus_client import get_metrics as _fn
    return json.dumps(_fn(source))


@server.tool()
def get_infra_state(source: str = "platform") -> str:
    from k8s.k8s_client import get_infra_state as _fn
    return json.dumps(_fn(source))


@server.tool()
def get_platform_config(agent_type: str = "platform") -> str:
    from k8s.k8s_client import get_platform_config as _fn
    return json.dumps(_fn(agent_type))


@server.tool()
def get_jenkins_state() -> str:
    from k8s.k8s_client import get_jenkins_state as _fn
    return json.dumps(_fn())


@server.tool()
def get_db_state() -> str:
    from k8s.k8s_client import get_db_state as _fn
    return json.dumps(_fn())


@server.tool()
def get_deployment_spec(name: str, namespace: str) -> str:
    from k8s.k8s_client import get_deployment_spec as _fn
    return json.dumps(_fn(name, namespace))


@server.tool()
def get_pod_memory_peak(service: str, namespace: str) -> str:
    from k8s.prometheus_client import get_pod_memory_peak as _fn
    return json.dumps(_fn(service, namespace))


@server.tool()
def get_configmap_any_namespace(name: str) -> str:
    from k8s.k8s_client import get_configmap_any_namespace as _fn
    return json.dumps(_fn(name))


@server.tool()
def execute_kubectl(command: str, reason: str = "", risk_level: str = "low") -> str:
    from k8s.kubectl_executor import execute_action as _fn
    result = _fn({"command": command, "reason": reason, "risk_level": risk_level})
    return json.dumps(result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(server.sse_app(), host="0.0.0.0", port=8001, log_level="warning")
