from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from mcp_layer.client import get_platform_config, get_jenkins_state, get_db_state
from agents.memory import get_runbooks, get_cache_match
from orchestrator.state import AgentState
from config.langfuse import trace_llm
from config.prompts import load_prompt
from config.logger import get_logger
import os, json, re
from dotenv import load_dotenv
from agents.llm_retry import invoke_with_retry

load_dotenv(override=True)

log = get_logger("agent.integration")

llm = ChatGroq(model=os.getenv("GROQ_MODEL"), api_key=os.getenv("GROQ_API_KEY"), temperature=0)


def _parse_llm_json(raw: str, context: str = "") -> dict:
    # strips <think>...</think> blocks from DeepSeek R1 and similar reasoning models
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
    print(f"  [INTEGRATION] Plan — {mode}  ({len(plan)} action(s))")
    print(sep)
    for i, a in enumerate(plan, 1):
        print(f"  [{i}] {a.get('command', '?')}")
        reason = a.get("reason", "")
        if reason:
            print(f"       {reason}")
    print(f"{sep}\n")


def run_integration(state: AgentState) -> AgentState:
    inc  = state["incident"]
    obs  = state["obs"]
    comm = state.get("comm", {})
    opa  = state.get("opa", {})

    config        = get_platform_config("integration")
    jenkins_state = get_jenkins_state()
    db_state      = get_db_state()
    logs          = obs.get("logs", [])

    if comm.get("responding_agent") == "integration":
        log.info("integration responding to platform with Jenkins/DB data", extra={
            "pipelines": [p.get("name") for p in jenkins_state.get("pipelines", [])],
            "databases": [d.get("host") for d in db_state.get("databases", [])],
            "request":   comm.get("extra_request"),
        })
        return {
            **state,
            "integration": {"config": config, "jenkins_state": jenkins_state, "db_state": db_state},
            "comm": {
                **comm,
                "extra_data": {
                    "integration_config": config,
                    "jenkins_state":      jenkins_state,
                    "db_state":           db_state,
                    "source":             "integration_agent",
                },
                "needs_more_data":  False,
                "responding_agent": "",
                "requesting_agent": "",
                "just_responded":   "integration",
            },
        }

    runbooks    = get_runbooks(f"Incident: {inc['alertname']}. Type: {obs.get('incident_type', '')}. Causes: {obs['incident_cause']} {obs.get('root_cause_hypothesis', '')}.")
    cache_match = get_cache_match(
        f"Incident: {inc['alertname']}. Service: {inc['service']}. Causes: {obs['incident_cause']} {obs.get('root_cause_hypothesis', '')}.",
        incident_type=obs.get("incident_type", ""),
    )

    if comm.get("just_responded") == "platform":
        extra = comm.get("extra_data", {})

        log.info("integration building plan with platform data", extra={
            "k8s_pods": [p.get("name") for p in extra.get("k8s_state", {}).get("pods", [])],
        })

        system, user = load_prompt(
            "integration_shared.j2",
            alertname=inc["alertname"],
            service=inc["service"],
            namespace=inc["namespace"],
            incident_cause=obs["incident_cause"],
            root_cause_hypothesis=obs.get("root_cause_hypothesis", ""),
            affected_components=obs.get("affected_components", []),
            jenkins_state=jenkins_state,
            db_state=db_state,
            config=config,
            logs=logs,
            extra=extra,
            runbooks=runbooks,
            cache_match=cache_match,
        )

        response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
        log.info("integration shared plan built", extra={"preview": response.content[:200]})
        trace_llm(name="integration_agent", input_text=user, output_text=response.content,
                model=os.getenv("GROQ_MODEL"), session_id=inc["incident_id"])

        parsed = _parse_llm_json(response.content, "integration shared")
        plan = parsed.get("actions")
        if not plan:
            log.critical("integration shared: LLM returned no actions — aborting", extra={"parsed": str(parsed)[:200]})
            raise RuntimeError("integration agent (shared): LLM returned no actionable plan")
        _print_plan("shared (platform data)", plan)
        log.info("integration shared plan sent to OPA", extra={"action_count": len(plan)})

        return {
            **state,
            "integration": {"config": config, "jenkins_state": jenkins_state, "db_state": db_state},
            "execution":   {**state.get("execution", {}), "remediation_plan": plan},
            "comm": {
                **comm,
                "active_agent":    "integration",
                "needs_more_data": False,
                "just_responded":  "",
            },
        }

    if opa.get("retry_count", 0) > 0 and not opa.get("approved"):
        log.warning("integration revising plan after OPA rejection", extra={
            "retry_count": opa.get("retry_count"),
            "opa_reason":  opa.get("reason"),
        })

        system, user = load_prompt(
            "integration_revision.j2",
            alertname=inc["alertname"],
            service=inc["service"],
            namespace=inc["namespace"],
            incident_cause=obs["incident_cause"],
            root_cause_hypothesis=obs.get("root_cause_hypothesis", ""),
            affected_components=obs.get("affected_components", []),
            jenkins_state=jenkins_state,
            db_state=db_state,
            config=config,
            logs=logs,
            runbooks=runbooks,
            cache_match=cache_match,
            refused_plan=state.get("execution", {}).get("remediation_plan", []),
            opa_reason=opa.get("reason"),
        )

        response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
        log.info("integration revised plan", extra={"preview": response.content[:200]})
        trace_llm(name="integration_agent", input_text=user, output_text=response.content,
                model=os.getenv("GROQ_MODEL"), session_id=inc["incident_id"])

        parsed = _parse_llm_json(response.content, "integration revision")
        plan = parsed.get("actions")
        if not plan:
            log.critical("integration revision: LLM returned no actions — aborting", extra={"parsed": str(parsed)[:200]})
            raise RuntimeError("integration agent (revision): LLM returned no actionable plan")
        _print_plan("post-OPA revision", plan)
        log.info("integration revised plan sent to OPA", extra={"action_count": len(plan)})

        return {
            **state,
            "integration": {"config": config, "jenkins_state": jenkins_state, "db_state": db_state},
            "execution":   {**state.get("execution", {}), "remediation_plan": plan},
            "comm": {
                **comm,
                "active_agent":    "integration",
                "needs_more_data": False,
                "just_responded":  "",
            },
        }

    k8s   = state.get("platform", {}).get("k8s_state", {})
    extra = comm.get("extra_data", {})

    log.info("integration normal resolution", extra={
        "incident":  inc["alertname"],
        "service":   inc["service"],
        "cause":     obs["incident_cause"],
        "pipelines": [p.get("name", "") + "->" + p.get("status", "")
                    for p in jenkins_state.get("pipelines", [])],
        "databases": [d.get("host", "") + " " + str(d.get("connections")) + "/" + str(d.get("max_connections"))
                    for d in db_state.get("databases", [])],
    })

    system, user = load_prompt(
        "integration_normal.j2",
        alertname=inc["alertname"],
        service=inc["service"],
        namespace=inc["namespace"],
        message=inc["message"],
        incident_cause=obs["incident_cause"],
        root_cause_hypothesis=obs.get("root_cause_hypothesis", ""),
        affected_components=obs.get("affected_components", []),
        jenkins_state=jenkins_state,
        db_state=db_state,
        config=config,
        logs=logs,
        k8s_extra=k8s or extra,
        runbooks=runbooks,
        cache_match=cache_match,
    )

    response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
    log.info("integration LLM decision", extra={"preview": response.content[:300]})
    trace_llm(name="integration_agent", input_text=user, output_text=response.content,
            model=os.getenv("GROQ_MODEL"), session_id=inc["incident_id"])

    result = _parse_llm_json(response.content, "integration normal") or {"needs_more_data": False}

    if result.get("needs_more_data") and not k8s and not extra:
        log.info("integration requesting platform data", extra={"request": result.get("extra_request")})
        return {
            **state,
            "integration": {"config": config, "jenkins_state": jenkins_state, "db_state": db_state},
            "comm": {
                **comm,
                "needs_more_data":  True,
                "extra_request":    result.get("extra_request"),
                "requesting_agent": "integration",
                "responding_agent": "platform",
                "just_responded":   "",
            },
        }

    plan = result.get("actions")
    if not plan:
        log.critical("integration normal: LLM returned no actions — aborting", extra={"parsed": str(result)[:200]})
        raise RuntimeError("integration agent (normal): LLM returned no actionable plan")
    _print_plan("normal", plan)
    log.info("integration plan sent to OPA", extra={
        "action_count": len(plan),
        "commands": [a.get("command") for a in plan],
    })

    return {
        **state,
        "integration": {"config": config, "jenkins_state": jenkins_state, "db_state": db_state},
        "execution":   {**state.get("execution", {}), "remediation_plan": plan},
        "comm": {
            **comm,
            "active_agent":    "integration",
            "needs_more_data": False,
            "just_responded":  "",
        },
    }
