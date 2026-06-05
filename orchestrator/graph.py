from langgraph.graph import StateGraph, END
from orchestrator.state import (
    AgentState, IncidentInfo, ObservabilityData,
    PlatformState, IntegrationState, CommunicationState,
    OPAState, ExecutionState,
)
from agents.observability import run_observability
from agents.platform_agent import run_platform
from agents.integration_agent import run_integration
from agents.opa_validator import validate_plan
from agents.executor import execute_plan
from agents.audit import record_audit
from agents.memory_writer import enrich_memory
from agents.notifier import notify_operator, notify_resolved_node, notify_unresolved_node
from orchestrator.post_check import post_check_node
from config.logger import get_logger
import os, time
from dotenv import load_dotenv

load_dotenv(override=True)

log = get_logger("orchestrator.graph")

_SEP = "═" * 58
_sep = "─" * 58


def _timed(name: str, fn):
    def wrapper(state: AgentState) -> AgentState:
        t0     = time.perf_counter()
        result = fn(state)
        elapsed = time.perf_counter() - t0
        timings = dict((result or state).get("timings", {}))
        timings[name] = timings.get(name, 0.0) + elapsed
        return {**(result or state), "timings": timings}
    return wrapper


def route_agent(state: AgentState) -> str:
    incident_type = state["obs"]["incident_type"]
    print(f"\n{_sep}")
    print(f"  [ROUTING] Selected agent: {incident_type.upper()}")
    print(f"{_sep}\n")
    log.info("routing agent", extra={"incident_type": incident_type})
    return incident_type


def after_platform(state: AgentState) -> str:
    comm = state.get("comm", {})
    if comm.get("needs_more_data", False):
        responding = comm.get("responding_agent", "")
        log.info("platform needs data", extra={
            "from":    responding,
            "request": comm.get("extra_request"),
        })
        return "ask_integration" if responding == "integration" else "ask_observability"

    if comm.get("just_responded") == "platform":
        log.info("platform responded -> return to integration")
        return "return_integration"

    return "validate"


def after_integration(state: AgentState) -> str:
    comm = state.get("comm", {})
    if comm.get("needs_more_data", False):
        responding = comm.get("responding_agent", "")
        log.info("integration needs data", extra={
            "from":    responding,
            "request": comm.get("extra_request"),
        })
        return "ask_platform" if responding == "platform" else "ask_observability"

    if comm.get("just_responded") == "integration":
        log.info("integration responded -> return to platform")
        return "return_platform"

    return "validate"


def after_execute(state: AgentState) -> str:
    if state.get("execution", {}).get("resolved", False):
        return "post_check"
    return "notify_unresolved"


def after_post_check(state: AgentState) -> str:
    confirmed = state.get("execution", {}).get("post_check_confirmed", False)
    log.info("post-check result", extra={"confirmed": confirmed})
    return "notify_resolved" if confirmed else "notify_unresolved"


def opa_decision(state: AgentState) -> str:
    opa    = state["opa"]
    active = state.get("comm", {}).get("active_agent", "platform")
    log.info("OPA decision", extra={"approved": opa["approved"], "retry": opa["retry_count"]})
    if opa["approved"]:
        return "execute"
    if opa["retry_count"] >= int(os.getenv("OPA_MAX_RETRIES", "2")):
        return "block"
    log.warning("OPA refused — revising", extra={"agent": active})
    return f"revise_{active}"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("observability",     _timed("observability",     run_observability))
    graph.add_node("platform",          _timed("planning",          run_platform))
    graph.add_node("integration",       _timed("planning",          run_integration))
    graph.add_node("opa_validate",      _timed("opa",               validate_plan))
    graph.add_node("execute",           _timed("execution",         execute_plan))
    graph.add_node("post_check",        _timed("post_check",        post_check_node))
    graph.add_node("notify_resolved",   _timed("notify",            notify_resolved_node))
    graph.add_node("notify_unresolved", _timed("notify",            notify_unresolved_node))
    graph.add_node("audit",             _timed("audit",             record_audit))
    graph.add_node("enrich_memory",     _timed("enrich_memory",     enrich_memory))
    graph.add_node("block",             _timed("notify",            notify_operator))

    graph.set_entry_point("observability")

    graph.add_conditional_edges("observability", route_agent, {
        "platform":    "platform",
        "integration": "integration",
    })
    graph.add_conditional_edges("platform", after_platform, {
        "validate":           "opa_validate",
        "ask_integration":    "integration",
        "ask_observability":  "observability",
        "return_integration": "integration",
    })
    graph.add_conditional_edges("integration", after_integration, {
        "validate":          "opa_validate",
        "ask_platform":      "platform",
        "ask_observability": "observability",
        "return_platform":   "platform",
    })
    graph.add_conditional_edges("opa_validate", opa_decision, {
        "execute":            "execute",
        "block":              "block",
        "revise_platform":    "platform",
        "revise_integration": "integration",
    })

    graph.add_conditional_edges("execute", after_execute, {
        "post_check":        "post_check",
        "notify_unresolved": "notify_unresolved",
    })
    graph.add_conditional_edges("post_check", after_post_check, {
        "notify_resolved":   "notify_resolved",
        "notify_unresolved": "notify_unresolved",
    })
    graph.add_edge("notify_resolved",   "audit")
    graph.add_edge("notify_unresolved", "audit")
    graph.add_edge("audit",             "enrich_memory")
    graph.add_edge("enrich_memory",     END)
    graph.add_edge("block",             "enrich_memory")

    return graph.compile()


pipeline = build_graph()


def run_pipeline(incident: dict):
    initial_state = AgentState(
        incident=IncidentInfo(
            incident_id=incident["incident_id"],
            alertname=incident["alertname"],
            service=incident["service"],
            namespace=incident["namespace"],
            message=incident["message"],
            timestamp=incident["timestamp"],
        ),
        obs=ObservabilityData(
            logs=[], metrics={}, infra_state={},
            incident_type="", incident_cause="",
            root_cause_hypothesis="", affected_components=[],
            classification={},
        ),
        platform=PlatformState(k8s_state={}, config={}),
        integration=IntegrationState(config={}, jenkins_state={}, db_state={}),
        comm=CommunicationState(
            active_agent="",
            needs_more_data=False,
            extra_request="",
            extra_data={},
            requesting_agent="",
            responding_agent="",
            just_responded="",
        ),
        opa=OPAState(approved=False, reason="", retry_count=0, blocked=False),
        execution=ExecutionState(
            remediation_plan=[],
            initial_plan=[],
            execution_result={},
            audit_trail=[],
            resolved=False,
            exec_error="",
            post_check_confirmed=False,
        ),
        timings={},
    )

    print(f"\n{_SEP}")
    print(f"  NEW INCIDENT  →  {incident['alertname']}")
    print(f"  Service    : {incident['service']}  |  Namespace : {incident['namespace']}")
    print(f"  ID         : {incident['incident_id']}")
    print(f"{_SEP}\n")

    t_pipeline_start = time.perf_counter()
    final_state      = pipeline.invoke(initial_state)
    total_s          = time.perf_counter() - t_pipeline_start

    exec_st  = final_state.get("execution", {})
    comm_st  = final_state.get("comm", {})
    opa_st   = final_state.get("opa", {})
    plan     = exec_st.get("remediation_plan", [])
    resolved = exec_st.get("resolved", False)
    agent    = comm_st.get("active_agent", "?")
    n_ok     = sum(1 for r in (exec_st.get("execution_result") or []) if r.get("status") == "success")

    print(f"\n{_SEP}")
    if opa_st.get("blocked", False):
        print(f"  STATUS  →  ✗ BLOCKED     |  Agent: {agent}  |  OPA reason: {opa_st.get('reason', '?')}")
    else:
        exec_results = exec_st.get("execution_result") or []
        errors = [r.get("detail", "?") for r in exec_results if r.get("status") == "error"]
        if not exec_results:
            print(f"  STATUS  →  ✗ NO ACTIONS  |  Agent: {agent}  |  Empty plan or all commands skipped")
        elif errors:
            print(f"  STATUS  →  ✗ EXEC FAILED |  Agent: {agent}  |  {errors[0]}")
        else:
            print(f"  STATUS  →  ✓ EXECUTED    |  Agent: {agent}  |  {n_ok}/{len(exec_results)} action(s) OK  |  awaiting post-check...")
    print(f"{_SEP}\n")

    timings = final_state.get("timings", {})
    _STAGE_ORDER = ["observability", "planning", "opa", "execution", "post_check", "notify", "audit", "enrich_memory"]
    print(f"\n{_SEP}")
    print(f"  RESPONSE TIME  →  {total_s:.1f}s total")
    for stage in _STAGE_ORDER:
        if stage in timings:
            print(f"  {stage:<16}: {timings[stage]:>6.1f}s")
    print(f"{_SEP}\n")

    log.info("pipeline complete", extra={
        "incident_id":  incident["incident_id"],
        "resolved":     exec_st.get("resolved", False),
        "active_agent": comm_st.get("active_agent", "?"),
        "opa_approved": opa_st.get("approved", False),
        "actions":      len(plan) if isinstance(plan, list) else 0,
        "exec_result":  exec_st.get("execution_result"),
        "total_s":      round(total_s, 2),
        "timings":      {k: round(v, 2) for k, v in timings.items()},
    })
    return final_state
