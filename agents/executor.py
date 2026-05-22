import re
from mcp_layer.client import execute_action
from orchestrator.state import AgentState
from config.logger import get_logger
from dotenv import load_dotenv

load_dotenv()

log = get_logger("agent.executor")

# Matches the RS-hash + pod-hash suffix on K8s pod names: e.g. -75fc6dcb95-j72nv
_K8S_POD_SUFFIX = re.compile(r'-[a-z0-9]{8,10}-[a-z0-9]{5}$')


def _base_name(component: str) -> str:
    """Return the deployment/daemonset name by stripping K8s pod hash suffixes."""
    return _K8S_POD_SUFFIX.sub('', component.lower())


def _is_allowed_target(command: str, affected: list, service: str) -> bool:
    if not affected:
        return True
    cmd = command.lower()
    if service and service.lower() in cmd:
        return True
    for c in affected:
        c_lower = c.lower()
        if c_lower in cmd:
            return True
        base = _base_name(c_lower)
        if base and base != c_lower and base in cmd:
            return True
    return False


def execute_plan(state: AgentState) -> AgentState:
    exec_st  = state.get("execution", {})
    comm     = state.get("comm", {})
    opa_st   = state.get("opa", {})
    inc      = state["incident"]
    obs      = state.get("obs", {})

    plan     = exec_st.get("remediation_plan") or []
    agent    = comm.get("active_agent", "platform")
    affected = obs.get("affected_components", [])
    service  = inc.get("service", "")

    if isinstance(plan, dict):
        plan = [plan]

    log.info("execution start", extra={"agent": agent, "action_count": len(plan)})

    results     = []
    new_entries = []
    all_ok      = True

    for i, action_item in enumerate(plan, 1):
        command = action_item.get("command", "")

        if not _is_allowed_target(command, affected, service):
            log.warning("command targets outside affected_components — skipped", extra={
                "command":  command,
                "affected": affected,
            })
            print(f"  [EXECUTOR] SKIPPED — command '{command[:60]}' not targeting affected_components {affected}")
            new_entries.append({
                "incident_id":      inc["incident_id"],
                "agent":            agent,
                "command":          command,
                "execution_result": {"status": "skipped", "detail": "command not targeting affected_components"},
                "opa_approved":     opa_st.get("approved", False),
            })
            continue

        log.info("executing command", extra={
            "index":   i,
            "total":   len(plan),
            "command": command,
            "reason":  action_item.get("reason"),
        })
        try:
            result = execute_action(action_item)
        except Exception as e:
            result = {"status": "error", "detail": str(e)}
            all_ok = False

        if result.get("status") == "error":
            log.error("command failed", extra={"index": i, "error": result.get("detail")})
            all_ok = False
        else:
            log.info("command success", extra={"index": i, "result": result})

        results.append(result)
        new_entries.append({
            "incident_id":      inc["incident_id"],
            "agent":            agent,
            "command":          command,
            "execution_result": result,
            "opa_approved":     opa_st.get("approved", False),
        })

        if result.get("status") == "error":
            log.warning("plan halted after action failure", extra={"index": i})
            break

    success_count = sum(1 for r in results if r.get("status") == "success")
    resolved      = all_ok and success_count > 0 and success_count == len(results)

    log.info("execution complete", extra={
        "resolved":      resolved,
        "success_count": success_count,
        "total":         len(results),
    })

    return {
        **state,
        "execution": {
            **exec_st,
            "execution_result": results,
            "audit_trail":      exec_st.get("audit_trail", []) + new_entries,
            "resolved":         resolved,
        },
    }
