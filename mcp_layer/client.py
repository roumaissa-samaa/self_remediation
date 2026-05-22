import os
import json
import asyncio
import concurrent.futures
from dotenv import load_dotenv

load_dotenv(override=True)

MCP_MODE       = os.getenv("MCP_MODE", "mock")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001/sse")


async def _call_tool(tool: str, args: dict):
    from mcp.client.sse import sse_client
    from mcp import ClientSession
    async with sse_client(url=MCP_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return json.loads(result.content[0].text)


def _sync_call(tool: str, args: dict):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _call_tool(tool, args)).result()


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


def execute_action(action: dict) -> dict:
    if MCP_MODE == "mock":
        print(f"[MOCK] Action executed: {action}")
        return {"status": "success", "action": action}
    return _sync_call("execute_kubectl", {
        "command":    action.get("command", ""),
        "reason":     action.get("reason", ""),
        "risk_level": action.get("risk_level", "low"),
    })
