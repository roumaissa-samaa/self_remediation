---
type: kubernetes
agent: Platform
---

# Runbook — Pod Not Ready (0/1 Ready)

**Symptom**: The pod is in `Running` state but receives no traffic from the Service. Applications report intermittent failures or the service endpoint is empty.
**Indicators**: `READY: 0/1` in `oc get pods`, `oc get endpoints <svc>` shows no addresses, `Readiness probe failed` in events.

---

## Ready vs Running — Key Difference

- **Running** = the container process started successfully.
- **Ready** = the container passed its readiness probe AND is included in Service endpoints.

A pod can be Running but not Ready. The Service only routes traffic to Ready pods.

---

## Common Causes

1. **Readiness probe failing** — the probe path returns a non-2xx status, or TCP port is not open yet.
2. **Application slow to initialize** — app takes longer than `initialDelaySeconds` to become ready.
3. **Wrong probe port or path** — probe is configured for a different port than what the app listens on.
4. **Application genuinely unhealthy** — DB connection failed, dependency unavailable, app in degraded mode.
5. **Init container still running** — main container not started yet because an init container is pending.
6. **Container listening on 127.0.0.1** — probe cannot reach it; app must listen on `0.0.0.0`.

---

## Diagnosis Steps

```bash
# Step 1 — Check readiness probe failure events
oc describe pod <pod-name> -n <namespace>
# Look for: "Readiness probe failed: ..."

# Step 2 — Verify endpoints for the Service
oc get endpoints <service-name> -n <namespace>
# If "(none)" → no ready pods behind the Service

# Step 3 — Check app logs for startup errors
oc logs <pod-name> -n <namespace> --tail=100

# Step 4 — Manually test the readiness endpoint from inside the pod
oc exec <pod-name> -n <namespace> -- curl -s -o /dev/null -w "%{http_code}" http://localhost:<port><path>
# Expected: 200. If 000 → not listening. If 404/503 → wrong path or app not ready.

# Step 5 — Check current probe configuration
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[0].readinessProbe}'
```

---

## Remediation

### Increase initialDelaySeconds (most common fix)
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/initialDelaySeconds","value":30}]'
```

### Correct the probe path
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/path","value":"/health"}]'
```

### Correct the probe port
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":8080}]'
```

### Remove readiness probe temporarily (to restore traffic while investigating)
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"remove","path":"/spec/template/spec/containers/0/readinessProbe"}]'
```

### Recommended probe configuration for web applications
```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 15
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
  successThreshold: 1
```

---

## Risk Level
- Increasing `initialDelaySeconds`: **low**
- Removing readiness probe: **medium** — traffic may reach an unhealthy pod
- Patching path/port: **low**

---

## Follow-up Actions
1. After patching: `oc get endpoints <service-name> -n <namespace> -w` — confirm pod IP appears.
2. Verify with: `oc exec <pod-name> -n <namespace> -- curl -s http://localhost:<port>/ready`
3. If the application is genuinely not ready (DB unreachable, dependency down), fix the underlying dependency.
4. Consider a `startupProbe` for apps with variable startup time — it disables liveness/readiness until the app signals it has started.
