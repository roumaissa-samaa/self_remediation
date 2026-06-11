import os
import json
import asyncio
import time
import concurrent.futures
from dotenv import load_dotenv

load_dotenv(override=True)

MCP_MODE       = os.getenv("MCP_MODE", "mock")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001/sse")

_MCP_RETRIES = 3
_MCP_RETRY_DELAY = 1.5


async def _call_tool(tool: str, args: dict):
    from mcp.client.sse import sse_client
    from mcp import ClientSession
    async with sse_client(url=MCP_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return json.loads(result.content[0].text)


def _sync_call(tool: str, args: dict):
    import logging
    last_exc = None
    for attempt in range(1, _MCP_RETRIES + 1):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _call_tool(tool, args)).result()
        except Exception as e:
            last_exc = e
            if attempt < _MCP_RETRIES:
                logging.getLogger("mcp.client").warning(
                    "MCP call '%s' failed (attempt %d/%d): %s — retrying in %.1fs",
                    tool, attempt, _MCP_RETRIES, e, _MCP_RETRY_DELAY,
                )
                time.sleep(_MCP_RETRY_DELAY)
    raise last_exc


def get_logs(source: str = "platform") -> list:
    if MCP_MODE == "mock":
        from mcp_layer.mock_data import MOCK_DATA
        return MOCK_DATA["observability"]["logs"]
    return _sync_call("get_logs", {"source": source})


def get_metrics(source: str = "platform") -> dict:
    if MCP_MODE == "mock":
        from mcp_layer.mock_data import MOCK_DATA
        return MOCK_DATA["observability"]["metrics"]
    return _sync_call("get_metrics", {"source": source})


def get_infra_state(source: str = "platform") -> dict:
    if MCP_MODE == "mock":
        from mcp_layer.mock_data import MOCK_DATA
        return MOCK_DATA["platform"]["infra_state"]
    return _sync_call("get_infra_state", {"source": source})


def get_platform_config(agent_type: str) -> dict:
    if MCP_MODE == "mock":
        from mcp_layer.mock_data import MOCK_DATA
        if agent_type == "platform":
            return MOCK_DATA["platform"]["platform_config"]
        return MOCK_DATA["integration"]["integration_config"]
    return _sync_call("get_platform_config", {"agent_type": agent_type})


def get_jenkins_state() -> dict:
    if MCP_MODE == "mock":
        from mcp_layer.mock_data import MOCK_DATA
        return MOCK_DATA["integration"]["jenkins_state"]
    return _sync_call("get_jenkins_state", {})


def get_db_state() -> dict:
    if MCP_MODE == "mock":
        from mcp_layer.mock_data import MOCK_DATA
        return MOCK_DATA["integration"]["db_state"]
    return _sync_call("get_db_state", {})


def get_deployment_spec(name: str, namespace: str) -> dict:
    if MCP_MODE == "mock":
        from mcp_layer.mock_data import MOCK_DATA
        return MOCK_DATA.get("deployment_specs", {}).get(name, {})
    try:
        return _sync_call("get_deployment_spec", {"name": name, "namespace": namespace})
    except Exception as e:
        import logging
        logging.getLogger("mcp.client").warning(
            "get_deployment_spec failed — continuing without spec: %s", e
        )
        return {}


def get_pod_memory_peak(service: str, namespace: str) -> dict:
    if MCP_MODE == "mock":
        return {}
    try:
        return _sync_call("get_pod_memory_peak", {"service": service, "namespace": namespace})
    except Exception as e:
        import logging
        logging.getLogger("mcp.client").warning("get_pod_memory_peak failed: %s", e)
        return {}


def get_rollout_revision_count(name: str, namespace: str) -> int:
    if MCP_MODE == "mock":
        return 0
    try:
        return _sync_call("get_rollout_revision_count", {"name": name, "namespace": namespace})
    except Exception as e:
        import logging
        logging.getLogger("mcp.client").warning("get_rollout_revision_count failed: %s", e)
        return 0


def get_configmap_refs(name: str, namespace: str) -> set:
    if MCP_MODE == "mock":
        return set()
    try:
        result = _sync_call("get_configmap_refs", {"name": name, "namespace": namespace})
        return set(result)
    except Exception as e:
        import logging
        logging.getLogger("mcp.client").warning("get_configmap_refs failed: %s", e)
        return set()


def get_configmap_any_namespace(name: str) -> dict:
    if MCP_MODE == "mock":
        return {}
    try:
        return _sync_call("get_configmap_any_namespace", {"name": name})
    except Exception as e:
        import logging
        logging.getLogger("mcp.client").warning("get_configmap_any_namespace failed: %s", e)
        return {}


def execute_action(action: dict) -> dict:
    if MCP_MODE == "mock":
        print(f"[MOCK] Action executed: {action}")
        return {"status": "success", "action": action}
    return _sync_call("execute_kubectl", {
        "command":    action.get("command", ""),
        "reason":     action.get("reason", ""),
        "risk_level": action.get("risk_level", "low"),
    })
