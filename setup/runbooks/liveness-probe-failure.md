---
type: kubernetes
agent: Platform
---

﻿# Runbook — Liveness Probe Failure / Readiness Probe Failure

**Symptom**: Kubernetes keeps restarting the container even though the application has no crash. The pod shows `CrashLoopBackOff` or restarts periodically despite apparently running.
**Indicators**: Events show `Liveness probe failed`, `Readiness probe failed`, `Killing container with id ... unhealthy`.

---

## Liveness vs Readiness vs Startup Probes

| Probe | Purpose | Effect on failure |
|-------|---------|-------------------|
| **Liveness** | Is the container still alive? | Container is killed and restarted |
| **Readiness** | Is the container ready to serve traffic? | Pod removed from Service endpoints (no traffic), not restarted |
| **Startup** | Has the container finished starting? | Container is killed if startup takes too long |

---

## Common Causes

1. **`initialDelaySeconds` too short** — probe starts checking before the application finishes initializing (common with JVM, Spring Boot, Django).
2. **`timeoutSeconds` too short** — the endpoint responds slowly under load; probe times out and declares the container unhealthy.
3. **Wrong probe path or port** — the HTTP path or TCP port in the probe spec doesn't match what the application exposes.
4. **Application is genuinely unhealthy** — deadlock, thread starvation, or memory pressure causing the health endpoint to hang.
5. **Probe checks an endpoint that requires authentication** — returns 401/403 which the probe interprets as failure.

---

## Diagnosis Steps

```bash
# Step 1 — Identify probe failure in events
oc describe pod <pod-name> -n <namespace>
# Look for:
#   Liveness probe failed: HTTP probe failed with statuscode: 503
#   Liveness probe failed: dial tcp ... connection refused
#   Killing container with id ...: unhealthy

# Step 2 — See the current probe configuration
oc get pod <pod-name> -n <namespace> -o json | \
  python3 -c "import sys,json; [print(c.get('livenessProbe'), c.get('readinessProbe')) for c in json.load(sys.stdin)['spec']['containers']]"

# Step 3 — Check restart pattern (is it periodic = probe, or immediate = crash)
oc get pod <pod-name> -n <namespace>
# Periodic restarts every few minutes → probe issue
# Immediate restart (back-off) → application crash

# Step 4 — Manually test the probe endpoint from inside the pod
oc exec <pod-name> -n <namespace> -- wget -qO- http://localhost:<port><path>
oc exec <pod-name> -n <namespace> -- curl -s -o /dev/null -w "%{http_code}" http://localhost:<port><path>
```

---

## Remediation

### Remove the liveness probe temporarily (to stop the restart loop)
```bash
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"remove","path":"/spec/template/spec/containers/0/livenessProbe"}]'
```

### Increase initialDelaySeconds (most common fix for slow-starting apps)
```bash
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/initialDelaySeconds","value":60}]'
```

### Increase timeoutSeconds and failureThreshold
```bash
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[{
    "op":"replace",
    "path":"/spec/template/spec/containers/0/livenessProbe/timeoutSeconds",
    "value":10
  },{
    "op":"replace",
    "path":"/spec/template/spec/containers/0/livenessProbe/failureThreshold",
    "value":5
  }]'
```

### Recommended probe settings for a slow-starting application
```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 45
  periodSeconds: 15
  timeoutSeconds: 10
  failureThreshold: 3
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  failureThreshold: 30
  periodSeconds: 10
```
> The `startupProbe` gives the app up to 5 minutes (30 × 10s) to start before liveness kicks in.

---

## Risk Level
- Removing liveness probe temporarily: **low** (disables health checking, use as a diagnostic step only)
- Increasing `initialDelaySeconds`: **low**
- Ignoring probe failures without investigating: **high** (may mask a real application deadlock)

---

## Follow-up Actions
1. After patching: confirm restarts stop — `oc get pod <pod-name> -n <namespace> -w`
2. Verify the health endpoint works: `oc exec <pod-name> -n <namespace> -- curl -s http://localhost:<port>/healthz`
3. Re-add a properly tuned liveness probe after confirming the correct `initialDelaySeconds`.
4. If the application is genuinely unhealthy (deadlock, memory), investigate logs and thread dumps.
