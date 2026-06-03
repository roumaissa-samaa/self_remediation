from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from mcp_layer.client import get_platform_config, get_infra_state
from agents.memory import get_runbooks, get_cache_match
from orchestrator.state import AgentState
from config.langfuse import trace_llm
from config.prompts import load_prompt
from config.logger import get_logger
import os, json, re
from dotenv import load_dotenv
from agents.llm_retry import invoke_with_retry

load_dotenv(override=True)

log = get_logger("agent.platform")

llm = ChatGroq(model=os.getenv("GROQ_MODEL"), api_key=os.getenv("GROQ_API_KEY"), temperature=0)


def _parse_llm_json(raw: str, context: str = "") -> dict:
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    label = f" ({context})" if context else ""
    log.error(f"LLM response not parseable{label}", extra={"preview": raw[:500]})
    return {}


def _print_plan(mode: str, plan: list) -> None:
    sep = "─" * 58
    print(f"\n{sep}")
    print(f"  [PLATFORM] Plan — {mode}  ({len(plan)} action(s))")
    print(sep)
    for i, a in enumerate(plan, 1):
        print(f"  [{i}] {a.get('command', '?')}")
        reason = a.get("reason", "")
        if reason:
            print(f"       {reason}")
    print(f"{sep}\n")


def run_platform(state: AgentState) -> AgentState:
    inc  = state["incident"]
    obs  = state["obs"]
    comm = state.get("comm", {})
    opa  = state.get("opa", {})

    k8s    = get_infra_state("platform")
    config = get_platform_config("platform")
    logs   = obs.get("logs", [])
    metrics = obs.get("metrics", {})

    if comm.get("responding_agent") == "platform":
        log.info("platform responding to integration with K8s data", extra={
            "pods":    [p["name"] for p in k8s.get("pods", [])],
            "request": comm.get("extra_request"),
        })
        return {
            **state,
            "platform": {"k8s_state": k8s, "config": config},
            "comm": {
                **comm,
                "extra_data": {
                    "k8s_state":       k8s,
                    "platform_config": config,
                    "source":          "platform_agent",
                },
                "needs_more_data":  False,
                "responding_agent": "",
                "requesting_agent": "",
                "just_responded":   "platform",
            },
        }

    runbooks    = get_runbooks(f"Incident: {inc['alertname']}. Type: {obs.get('incident_type', '')}. Causes: {obs['incident_cause']} {obs.get('root_cause_hypothesis', '')}.")
    cache_match = get_cache_match(f"Incident: {inc['alertname']}. Service: {inc['service']}. Causes: {obs['incident_cause']} {obs.get('root_cause_hypothesis', '')}.")

    if comm.get("just_responded") == "integration":
        extra = comm.get("extra_data", {})

        log.info("platform building plan with integration data", extra={
            "pipelines": [p.get("name") for p in extra.get("jenkins_state", {}).get("pipelines", [])],
        })

        system, user = load_prompt(
            "platform_shared.j2",
            alertname=inc["alertname"],
            service=inc["service"],
            namespace=inc["namespace"],
            incident_cause=obs["incident_cause"],
            root_cause_hypothesis=obs.get("root_cause_hypothesis", ""),
            affected_components=obs.get("affected_components", []),
            k8s=k8s,
            config=config,
            logs=logs,
            metrics=metrics,
            extra=extra,
            runbooks=runbooks,
            cache_match=cache_match,
        )

        response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
        log.info("platform shared plan built", extra={"preview": response.content[:200]})
        trace_llm(name="platform_agent", input_text=user, output_text=response.content,
                  model=os.getenv("GROQ_MODEL"), session_id=inc["incident_id"])

        parsed = _parse_llm_json(response.content, "platform shared")
        plan = parsed.get("actions")
        if not plan:
            log.critical("platform shared: LLM returned no actions — aborting", extra={"parsed": str(parsed)[:200]})
            raise RuntimeError("platform agent (shared): LLM returned no actionable plan")
        _print_plan("shared (integration data)", plan)
        log.info("platform shared plan sent to OPA", extra={"action_count": len(plan)})

        return {
            **state,
            "platform":  {"k8s_state": k8s, "config": config},
            "execution": {**state.get("execution", {}), "remediation_plan": plan},
            "comm": {
                **comm,
                "active_agent":    "platform",
                "needs_more_data": False,
                "just_responded":  "",
            },
        }

    if opa.get("retry_count", 0) > 0 and not opa.get("approved"):
        log.warning("platform revising plan after OPA rejection", extra={
            "retry_count": opa.get("retry_count"),
            "opa_reason":  opa.get("reason"),
        })

        system, user = load_prompt(
            "platform_revision.j2",
            alertname=inc["alertname"],
            service=inc["service"],
            namespace=inc["namespace"],
            message=inc["message"],
            incident_cause=obs["incident_cause"],
            root_cause_hypothesis=obs.get("root_cause_hypothesis", ""),
            affected_components=obs.get("affected_components", []),
            k8s=k8s,
            config=config,
            logs=logs,
            metrics=metrics,
            runbooks=runbooks,
            cache_match=cache_match,
            refused_plan=state.get("execution", {}).get("remediation_plan", []),
            opa_reason=opa.get("reason"),
        )

        response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
        log.info("platform revised plan", extra={"preview": response.content[:200]})
        trace_llm(name="platform_agent", input_text=user, output_text=response.content,
                  model=os.getenv("GROQ_MODEL"), session_id=inc["incident_id"])

        parsed = _parse_llm_json(response.content, "platform revision")
        plan = parsed.get("actions")
        if not plan:
            log.critical("platform revision: LLM returned no actions — aborting", extra={"parsed": str(parsed)[:200]})
            raise RuntimeError("platform agent (revision): LLM returned no actionable plan")
        _print_plan("post-OPA revision", plan)
        log.info("platform revised plan sent to OPA", extra={"action_count": len(plan)})

        return {
            **state,
            "platform":  {"k8s_state": k8s, "config": config},
            "execution": {**state.get("execution", {}), "remediation_plan": plan},
            "comm": {
                **comm,
                "active_agent":    "platform",
                "needs_more_data": False,
                "just_responded":  "",
            },
        }

    extra = comm.get("extra_data", {})

    log.info("platform normal resolution", extra={
        "incident": inc["alertname"],
        "service":  inc["service"],
        "cause":    obs["incident_cause"],
        "pods":     [p["name"] + ":" + p["status"] for p in k8s.get("pods", [])],
    })

    system, user = load_prompt(
        "platform_normal.j2",
        alertname=inc["alertname"],
        service=inc["service"],
        namespace=inc["namespace"],
        message=inc["message"],
        incident_cause=obs["incident_cause"],
        root_cause_hypothesis=obs.get("root_cause_hypothesis", ""),
        affected_components=obs.get("affected_components", []),
        k8s=k8s,
        config=config,
        metrics=metrics,
        logs=logs,
        runbooks=runbooks,
        cache_match=cache_match,
    )

    response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
    log.info("platform LLM decision", extra={"preview": response.content[:300]})
    trace_llm(name="platform_agent", input_text=user, output_text=response.content,
              model=os.getenv("GROQ_MODEL"), session_id=inc["incident_id"])

    result = _parse_llm_json(response.content, "platform normal") or {"needs_more_data": False}

    if result.get("needs_more_data") and not extra:
        log.info("platform requesting integration data", extra={"request": result.get("extra_request")})
        return {
            **state,
            "platform": {"k8s_state": k8s, "config": config},
            "comm": {
                **comm,
                "needs_more_data":  True,
                "extra_request":    result.get("extra_request"),
                "requesting_agent": "platform",
                "responding_agent": "integration",
                "just_responded":   "",
            },
        }

    plan = result.get("actions")
    if not plan:
        log.critical("platform normal: LLM returned no actions — aborting", extra={"parsed": str(result)[:200]})
        raise RuntimeError("platform agent (normal): LLM returned no actionable plan")
    _print_plan("normal", plan)
    log.info("platform plan sent to OPA", extra={
        "action_count": len(plan),
        "commands": [a.get("command") for a in plan],
    })

    return {
        **state,
        "platform":  {"k8s_state": k8s, "config": config},
        "execution": {**state.get("execution", {}), "remediation_plan": plan},
        "comm": {
            **comm,
            "active_agent":    "platform",
            "needs_more_data": False,
            "just_responded":  "",
        },
    }
