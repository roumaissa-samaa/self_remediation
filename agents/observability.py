from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from mcp_layer.client import get_logs, get_metrics, get_infra_state
from orchestrator.state import AgentState
from config.langfuse import trace_llm
from config.prompts import load_prompt
from config.logger import get_logger
import os, json, re
from dotenv import load_dotenv
from agents.llm_retry import invoke_with_retry

load_dotenv(override=True)

log = get_logger("agent.observability")

llm = ChatGroq(
    model=os.getenv("GROQ_MODEL"),
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
)


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _print_classification(inc: dict, c: dict) -> None:
    sep = "─" * 58
    print(f"\n{sep}")
    print(f"  [OBSERVABILITY] {inc['alertname']}  |  {inc['service']}")
    print(sep)
    print(f"  Type       : {c.get('incident_type', '?')}")
    print(f"  Cause      : {c.get('incident_cause', '?')}")
    hyp = c.get("root_cause_hypothesis", "")
    if hyp:
        print(f"  Hypothesis : {hyp[:115]}")
    comps = c.get("affected_components", [])
    if comps:
        print(f"  Components : {', '.join(comps)}")
    print(f"  Confidence : {c.get('confidence', '?')}")
    print(f"{sep}\n")


def _fallback_classification() -> dict:
    return {
        "incident_type":         "platform",
        "incident_cause":        "cause undetermined",
        "root_cause_hypothesis": "",
        "affected_components":   [],
        "confidence":            "low",
        "key_signals":           [],
    }


def run_observability(state: AgentState) -> AgentState:
    inc = state["incident"]

    logs_platform       = get_logs("platform")
    metrics_platform    = get_metrics("platform")
    infra_platform      = get_infra_state("platform")
    logs_integration    = get_logs("integration")
    metrics_integration = get_metrics("integration")
    infra_integration   = get_infra_state("integration")


    system, user = load_prompt(
        "observability.j2",
        alertname=inc["alertname"],
        service=inc["service"],
        namespace=inc["namespace"],
        message=inc["message"],
        logs_platform=logs_platform,
        metrics_platform=metrics_platform,
        infra_platform=infra_platform,
        logs_integration=logs_integration,
        metrics_integration=metrics_integration,
        infra_integration=infra_integration,
    )

    response = invoke_with_retry(llm, [SystemMessage(content=system), HumanMessage(content=user)])
    log.info("observability LLM response", extra={"preview": response.content[:300]})

    trace_llm(
        name="observability",
        input_text=user,
        output_text=response.content,
        model=os.getenv("GROQ_MODEL"),
        session_id=inc["incident_id"],
    )

    content = _strip_think(response.content)
    try:
        classification = json.loads(content)
    except Exception:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            try:
                classification = json.loads(match.group())
            except Exception:
                log.warning("observability JSON parse failed — using fallback")
                classification = _fallback_classification()
        else:
            log.warning("observability no JSON found in response — using fallback")
            classification = _fallback_classification()

    _print_classification(inc, classification)
    log.info("observability classification", extra={
        "type":       classification.get("incident_type"),
        "confidence": classification.get("confidence"),
        "components": classification.get("affected_components"),
        "hypothesis": classification.get("root_cause_hypothesis", "")[:150],
    })

    incident_type = classification.get("incident_type", "")

    metric_overlap = set(metrics_platform) & set(metrics_integration)
    if metric_overlap:
        log.warning("metric key conflict: integration overwrites platform values", extra={"keys": sorted(metric_overlap)})

    infra_overlap = set(infra_platform) & set(infra_integration)
    if infra_overlap:
        log.warning("infra_state key conflict: integration overwrites platform values", extra={"keys": sorted(infra_overlap)})

    return {
        **state,
        "obs": {
            **state.get("obs", {}),
            "logs":                  logs_platform + logs_integration,
            "metrics":               {**metrics_platform, **metrics_integration},
            "infra_state":           {**infra_platform, **infra_integration},
            "incident_type":         incident_type,
            "incident_cause":        classification.get("incident_cause", ""),
            "root_cause_hypothesis": classification.get("root_cause_hypothesis", ""),
            "affected_components":   classification.get("affected_components", []),
            "classification":        classification,
        },
        "comm": {
            **state.get("comm", {}),
            "active_agent": incident_type,
        },
    }
