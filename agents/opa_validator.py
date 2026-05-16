import os
import shlex
import requests
from dotenv import load_dotenv
from orchestrator.state import AgentState
from config.logger import get_logger

load_dotenv(override=True)

log = get_logger("agent.opa")


def _opa_base() -> str:
    return (
        os.getenv("OPA_URL")
        or os.getenv("OPA_PLATFORM_URL")
        or os.getenv("OPA_INTEGRATION_URL")
        or "http://localhost:8181"
    ).rstrip("/")


def _parse_command(command: str) -> dict:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    if not parts:
        return {"tool": "", "verb": "", "subverb": "", "resource": "", "target": "", "namespace": "", "replicas": None}

    tool = parts[0]
    parsed = {"tool": tool, "verb": "", "subverb": "", "resource": "", "target": "", "namespace": "", "replicas": None}

    if tool == "kubectl" and len(parts) > 1:
        parsed["verb"] = parts[1]

        start = 2
        if parts[1] == "rollout" and len(parts) > 2 and not parts[2].startswith("-"):
            parsed["subverb"] = parts[2]
            start = 3

        for part in parts[start:]:
            if part.startswith("-"):
                continue
            if "/" in part:
                res, tgt = part.split("/", 1)
                parsed["resource"] = parsed["resource"] or res
                parsed["target"] = parsed["target"] or tgt
                break
            elif not parsed["resource"]:
                parsed["resource"] = part
            elif not parsed["target"]:
                parsed["target"] = part
                break

        for i, part in enumerate(parts):
            if part in ("-n", "--namespace") and i + 1 < len(parts):
                parsed["namespace"] = parts[i + 1]
            elif part.startswith("--namespace="):
                parsed["namespace"] = part.split("=", 1)[1]
            elif part.startswith("--replicas="):
                try:
                    parsed["replicas"] = int(part.split("=")[1])
                except ValueError:
                    pass

    elif tool == "jenkins-cli" and len(parts) > 1:
        parsed["verb"] = parts[1]
        if len(parts) > 2:
            parsed["target"] = parts[2]

    return parsed


def _call_opa(opa_url: str, opa_input: dict) -> tuple[bool, str]:
    try:
        response = requests.post(opa_url, json={"input": opa_input}, timeout=15)
        payload  = response.json()
        approved = payload.get("result") is True and response.status_code < 400
    except Exception as e:
        return False, f"OPA error: {e}"

    if approved:
        return True, "approved"

    reason_url = opa_url.replace("/allow", "/deny_reason")
    try:
        rj     = requests.post(reason_url, json={"input": opa_input}, timeout=15).json()
        reason = rj.get("result") or rj.get("message") or "Command not authorized by OPA policy"
    except Exception:
        reason = "Command not authorized by OPA policy"
    return False, reason


def validate_plan(state: AgentState) -> AgentState:
    comm        = state.get("comm", {})
    opa_st      = state.get("opa", {})
    exec_st     = state.get("execution", {})
    raw_agent   = comm.get("active_agent") or "platform"
    agent       = str(raw_agent).strip().lower()
    plan        = exec_st.get("remediation_plan") or []
    retry_count = opa_st.get("retry_count", 0)

    if isinstance(plan, dict):
        plan = [plan]

    opa_url = f"{_opa_base()}/v1/data/remediation/allow"

    sep = "─" * 58
    print(f"\n{sep}")
    print(f"  [OPA] Validation — agent: {agent}  (attempt {retry_count + 1}, {len(plan)} action(s))")
    print(sep)

    log.info("OPA validation start", extra={
        "agent":   agent,
        "actions": len(plan),
        "attempt": retry_count + 1,
    })

    extra_data  = comm.get("extra_data", {})
    is_shared   = bool(extra_data.get("source"))
    other_agent = "integration" if agent == "platform" else "platform"

    for i, action_item in enumerate(plan, 1):
        command = str(action_item.get("command", "")).strip()
        parsed  = _parse_command(command)

        opa_input = {
            "agent":     agent,
            "command":   command,
            "tool":      parsed["tool"],
            "verb":      parsed["verb"],
            "subverb":   parsed["subverb"],
            "resource":  parsed["resource"],
            "target":    parsed["target"],
            "namespace": parsed["namespace"],
            "replicas":  parsed["replicas"],
            "reason":    action_item.get("reason", ""),
        }
        approved, reason = _call_opa(opa_url, opa_input)

        cross = False
        if not approved and is_shared:
            other_input = {**opa_input, "agent": other_agent}
            approved, reason = _call_opa(opa_url, other_input)
            cross = approved

        cmd_preview = command[:50] + "..." if len(command) > 50 else command
        if approved:
            label = f"✓ APPROVED {'(cross-agent)' if cross else ''}"
        else:
            label = f"✗ REFUSED  — {reason}"
        print(f"  [{i}] {cmd_preview:<55} {label}")

        log.info("OPA command result", extra={
            "index":    i,
            "command":  command,
            "approved": approved,
            "cross":    cross,
            "reason":   reason if not approved else None,
        })

        if not approved:
            new_retry = retry_count + 1
            print(f"{sep}\n")
            log.warning("OPA refused command", extra={"command": command, "retry_count": new_retry})
            return {
                **state,
                "opa": {
                    **opa_st,
                    "approved":    False,
                    "reason":      f"Command [{i}] '{command[:80]}' refused: {reason}",
                    "retry_count": new_retry,
                },
            }

    print(f"  → All commands approved")
    print(f"{sep}\n")
    log.info("OPA approved all commands", extra={"action_count": len(plan)})
    return {
        **state,
        "opa": {
            **opa_st,
            "approved":    True,
            "reason":      "Plan approved",
            "retry_count": retry_count,
        },
    }
