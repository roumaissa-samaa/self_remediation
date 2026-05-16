---
type: kubernetes
agent: Platform
---

﻿# Runbook — CrashLoopBackOff

**Symptom**: The pod starts, crashes immediately, and Kubernetes keeps restarting it with exponential back-off delay (10s → 20s → 40s → ... → 5min).
**Indicators**: `Status: CrashLoopBackOff`, `Restarts > 3`, back-off delay visible in events.

---

## Exit Code Reference

| Exit Code | Meaning | Typical Cause |
|-----------|---------|---------------|
| 0 | Clean exit | Entrypoint finished — not a long-running process |
| 1 | General error | Application exception, bad script, missing argument |
| 2 | Misuse of shell | Bash syntax error |
| 137 | SIGKILL (128+9) | OOMKilled or manually killed |
| 139 | Segmentation fault | Memory access violation in native code |
| 143 | SIGTERM (128+15) | Graceful shutdown signal, but liveness probe killed it |

---

## Common Causes

1. **Bad container command or args** — entrypoint script exits immediately with code 1.
2. **Missing environment variable or secret** — application crashes on startup due to missing config.
3. **Database/API unreachable** — application cannot connect on startup and fails fast.
4. **Liveness probe too aggressive** — `initialDelaySeconds` too short, probe kills the pod before it finishes starting.
5. **OOMKilled on startup** — memory limit too low even for the initialization phase (exit code 137).
6. **Port binding conflict** — application fails to bind to the specified port.

---

## Diagnosis Steps

```bash
# Step 1 — Check restart count and last exit code
oc describe pod <pod-name> -n <namespace>
# Look for: Last State > Terminated > Exit Code, Reason

# Step 2 — Read logs from the PREVIOUS crashed container (most important)
oc logs <pod-name> -n <namespace> --previous --tail=100

# Step 3 — Read current container logs (if it's still running briefly)
oc logs <pod-name> -n <namespace> --tail=50

# Step 4 — Check recent events
oc get events -n <namespace> \
  --field-selector involvedObject.name=<pod-name> \
  --sort-by=.lastTimestamp

# Step 5 — Inspect container spec (command, args, env, probes)
oc get pod <pod-name> -n <namespace> -o json | \
  python3 -c "import sys,json; spec=json.load(sys.stdin)['spec']; [print(c['name'], c.get('command'), c.get('args'), c.get('livenessProbe')) for c in spec['containers']]"
```

---

## Remediation by Cause

### Cause: Persistent irrecoverable crash — container always exits 1, cannot be fixed by restarting
Use action **scale_deployment** with replicas=0 to stop the restart loop immediately.
Deleting the pod does not help — the Deployment recreates it with the same broken config and it crashes again.
Scaling to 0 stops Kubernetes from restarting the container and stops Alertmanager from re-firing the alert.
Once the root cause is fixed (bad image, missing config, broken entrypoint), scale back up to 1 or more replicas.

### Cause: Bad entrypoint args (exit code 1, container launches but crashes immediately)
Use action **scale_deployment** with replicas=0 to stop the crash loop, then fix the Deployment spec.
If a known good previous revision exists, use **rollback_deployment** to revert to it.

### Cause: Liveness probe too aggressive
Use action **patch_deployment** to remove or adjust the liveness probe:
```json
[{"op":"remove","path":"/spec/template/spec/containers/0/livenessProbe"}]
```
Then reconfigure with a proper initialDelaySeconds (at least 30s for JVM apps).

### Cause: OOMKilled on startup (exit code 137)
Use action **patch_deployment** to increase the memory limit on the Deployment.
Strategic merge patch:
```json
{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","resources":{"limits":{"memory":"512Mi"}}}]}}}}
```

### Cause: Rollback a bad deployment
Use action **rollback_deployment** to revert to the previous known-good revision.

---

## Risk Level
- Reading logs and events: **low**
- Patching liveness probe: **low** (temporarily disables health checking)
- Rollback: **medium** (reverts code changes)
- Force delete + recreate: **medium** (brief downtime, only as last resort)

---

## Follow-up Actions
1. After fixing, monitor: `oc get pod <pod-name> -n <namespace> -w`
2. Confirm restarts stop increasing.
3. If the fix was a rollback, identify and fix the root cause in the new image before redeploying.
