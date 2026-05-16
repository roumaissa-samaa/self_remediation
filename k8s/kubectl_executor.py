import os
import shlex
import subprocess
from config.logger import get_logger

log = get_logger("mcp.executor")


def execute_action(action: dict) -> dict:
    command = action.get("command", "").strip()
    if not command:
        return {"status": "error", "detail": "No command provided"}

    log.info("executing command", extra={"command": command})

    try:
        parts = shlex.split(command)
    except ValueError as e:
        return {"status": "error", "detail": f"Invalid command syntax: {e}"}

    if not parts:
        return {"status": "error", "detail": "Empty command after parsing"}

    # drain needs a longer timeout
    timeout = 120 if len(parts) > 1 and parts[1] == "drain" else 30

    ok, out = _run(parts, timeout=timeout)
    return {"status": "success" if ok else "error", "detail": out}


def _run(args: list, timeout: int = 30) -> tuple[bool, str]:
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    output = r.stdout.strip() or r.stderr.strip()
    return r.returncode == 0, output
