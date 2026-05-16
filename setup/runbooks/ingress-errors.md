---
type: kubernetes
agent: Platform
---

# Runbook — Ingress / Route 502 / 504 Gateway Error

**Symptom**: The application URL returns HTTP 502 (Bad Gateway) or 504 (Gateway Timeout).
**Indicators**: 502/504 errors in browser or `curl`, HAProxy/Nginx Ingress Controller logs show upstream errors.

---

## 502 vs 504 — Key Difference

| Code | Meaning | Typical Cause |
|------|---------|---------------|
| **502** | Bad Gateway | Backend pod crashed or returned an invalid HTTP response |
| **504** | Gateway Timeout | Backend pod is alive but too slow to respond within the timeout |

---

## Common Causes

1. **All pods crash / CrashLoopBackOff** — no healthy backend for the Ingress to proxy to.
2. **Readiness probe failing** — pods are Running but removed from Service endpoints.
3. **Application timeout** — heavy request (large payload, slow DB query) exceeds the Ingress `proxy-read-timeout`.
4. **Service selector mismatch** — Ingress → Service → no matching pods (endpoints empty).
5. **Wrong backend port** — Ingress `servicePort` does not match the Service/container port.
6. **Router pod unhealthy** — OpenShift HAProxy router itself is overloaded or crashing.

---

## Diagnosis Steps

```bash
# Step 1 — Check if the Route/Ingress has valid endpoints behind it
oc get endpoints <service-name> -n <namespace>
# "(none)" = no ready pods → fix the pods first

# Step 2 — Check pod health
oc get pods -n <namespace>
oc describe pod <pod-name> -n <namespace>

# Step 3 — Check Ingress Controller / Router logs (OpenShift)
oc logs -n openshift-ingress -l ingresscontroller.operator.openshift.io/deployment-ingresscontroller=default --tail=100

# Step 4 — Check Service port and selector
oc get service <service-name> -n <namespace> -o yaml
# Verify: spec.ports[].targetPort matches container port
# Verify: spec.selector matches pod labels

# Step 5 — Test directly from inside the cluster
oc run debug-curl --image=curlimages/curl --restart=Never -n <namespace> --rm -it \
  -- curl -v http://<service-name>:<port>/healthz
```

---

## Remediation

### Fix — pods not ready (most common cause of 503/502)
See runbooks: `pod-not-ready.md`, `liveness-probe-failure.md`, `crashloopbackoff.md`.

### Fix — Service selector mismatch
```bash
# Get pod labels
oc get pods -n <namespace> --show-labels

# Patch the Service selector to match
oc patch service/<service-name> -n <namespace> \
  -p '{"spec":{"selector":{"app":"<correct-label>"}}}'
```

### Fix — wrong Service port
```bash
oc patch service/<service-name> -n <namespace> \
  -p '{"spec":{"ports":[{"port":80,"targetPort":8080,"protocol":"TCP"}]}}'
```

### Fix — 504 timeout (increase timeout on OpenShift Route)
```bash
oc annotate route <route-name> -n <namespace> \
  haproxy.router.openshift.io/timeout=120s
```

### Fix — Router pod overloaded
```bash
# Check Router pod resource usage
oc adm top pods -n openshift-ingress

# Restart Router if unresponsive
oc rollout restart deployment/router-default -n openshift-ingress
```

---

## Risk Level
- Patching Service selector/port: **low**
- Increasing Route timeout: **low**
- Restarting Router: **high** — brief disruption for all Routes in the cluster

---

## Follow-up Actions
1. After fix: `curl -o /dev/null -s -w "%{http_code}" https://<route-url>` — confirm 200.
2. Set up a synthetic monitor (uptime check) on the Route URL.
3. Review application response times — if regularly hitting timeouts, optimize the slow endpoints.
