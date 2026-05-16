import os
from dotenv import load_dotenv

load_dotenv(override=True)

MCP_MODE = os.getenv("MCP_MODE", "mock")

def get_logs(source: str = "observability") -> list:
    if MCP_MODE == "mock":
        from mcp.mock_data import MOCK_DATA
        return MOCK_DATA["observability"]["logs"]
    if MCP_MODE == "real":
        from k8s.prometheus_client import get_logs as _get_logs
        return _get_logs(source)
    raise NotImplementedError("Real MCP not configured")

def get_metrics(source: str = "observability") -> dict:
    if MCP_MODE == "mock":
        from mcp.mock_data import MOCK_DATA
        return MOCK_DATA["observability"]["metrics"]
    if MCP_MODE == "real":
        from k8s.prometheus_client import get_metrics as _get_metrics
        return _get_metrics(source)
    raise NotImplementedError("Real MCP not configured")

def get_infra_state(source: str = "platform") -> dict:
    if MCP_MODE == "mock":
        from mcp.mock_data import MOCK_DATA
        return MOCK_DATA["platform"]["infra_state"]
    if MCP_MODE == "real":
        from k8s.k8s_client import get_infra_state as _get_infra_state
        return _get_infra_state(source)
    raise NotImplementedError("Real MCP not configured")

def get_platform_config(agent_type: str) -> dict:
    if MCP_MODE == "mock":
        from mcp.mock_data import MOCK_DATA
        if agent_type == "platform":
            return MOCK_DATA["platform"]["platform_config"]
        else:
            return MOCK_DATA["integration"]["integration_config"]
    if MCP_MODE == "real":
        from k8s.k8s_client import get_platform_config as _get_platform_config
        return _get_platform_config(agent_type)
    raise NotImplementedError("Real MCP not configured")

def get_jenkins_state() -> dict:
    if MCP_MODE == "mock":
        from mcp.mock_data import MOCK_DATA
        return MOCK_DATA["integration"]["jenkins_state"]
    if MCP_MODE == "real":
        from k8s.k8s_client import get_jenkins_state as _get_jenkins_state
        return _get_jenkins_state()
    raise NotImplementedError("Real MCP not configured")

def get_db_state() -> dict:
    if MCP_MODE == "mock":
        from mcp.mock_data import MOCK_DATA
        return MOCK_DATA["integration"]["db_state"]
    if MCP_MODE == "real":
        from k8s.k8s_client import get_db_state as _get_db_state
        return _get_db_state()
    raise NotImplementedError("Real MCP not configured")

def execute_action(action: dict) -> dict:
    if MCP_MODE == "mock":
        print(f"[MOCK] Action executed: {action}")
        return {"status": "success", "action": action}
    if MCP_MODE == "real":
        from k8s.kubectl_executor import execute_action as _execute_action
        return _execute_action(action)
    raise NotImplementedError("Real MCP not configured")
