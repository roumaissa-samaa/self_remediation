---
type: kubernetes
agent: Platform
---

# Runbook — OpenShift Route Unavailable (503 / TLS Error)

**Symptom**: The Route URL returns `503 Application is not available`, a TLS error, or times out.
**Indicators**: Browser shows "Application is not available", `curl` returns 503, or TLS handshake failure.

---

## How OpenShift Routes Work

An OpenShift `Route` exposes a `Service` through the HAProxy-based Router (Ingress Controller). Traffic flows: `Client → Router → Service → Pod`. A 503 from the Router means it cannot reach any healthy pod endpoint.

---

## Common Causes

1. **No ready pods** — all pods are in CrashLoopBackOff, Pending, or failing readiness probe.
2. **Wrong Service port** — Route `targetPort` does not match the container's actual port.
3. **Service selector mismatch** — Service labels do not match pod labels → empty endpoints.
4. **TLS certificate expired** — edge/passthrough TLS cert is expired.
5. **Route points to wrong Service** — `spec.to.name` references a non-existent Service.
6. **Router pod unhealthy** — the OpenShift Ingress Controller itself is down.

---

## Diagnosis Steps

```bash
# Step 1 — Check Route config and TLS
oc get route <route-name> -n <namespace> -o yaml
oc describe route <route-name> -n <namespace>

# Step 2 — Check if Service has endpoints (pods behind it)
oc get endpoints <service-name> -n <namespace>
# If endpoints show "(none)" → no ready pods

# Step 3 — Check Service selector vs pod labels
oc get service <service-name> -n <namespace> -o jsonpath='{.spec.selector}'
oc get pods -n <namespace> --show-labels

# Step 4 — Check pod readiness
oc get pods -n <namespace>
oc describe pod <pod-name> -n <namespace>  # look for readiness probe failures

# Step 5 — Check Router pods
oc get pods -n openshift-ingress
```

---

## Remediation

### Fix — No ready pods → fix the underlying pod issue
See runbooks: `liveness-probe-failure.md`, `crashloopbackoff.md`, `pod-not-ready.md`.

### Fix — Wrong Service port
```bash
oc patch service/<service-name> -n <namespace> \
  -p '{"spec":{"ports":[{"port":80,"targetPort":8080,"protocol":"TCP"}]}}'
```

### Fix — Service selector mismatch
```bash
# Check pod labels
oc get pod <pod-name> -n <namespace> --show-labels

# Update Service selector to match pod labels
oc patch service/<service-name> -n <namespace> \
  -p '{"spec":{"selector":{"app":"<correct-label-value>"}}}'
```

### Fix — Recreate Route with correct TLS (edge termination)
```bash
oc delete route <route-name> -n <namespace>
oc create route edge <route-name> \
  --service=<service-name> \
  --port=<port> \
  --hostname=<host.apps.cluster.example.com> \
  -n <namespace>
```

### Fix — Route points to wrong Service
```bash
oc patch route <route-name> -n <namespace> \
  -p '{"spec":{"to":{"name":"<correct-service-name>"}}}'
```

### Fix — Router pods down (cluster-admin required)
```bash
oc rollout restart deployment/router-default -n openshift-ingress
```

---

## Risk Level
- Patching Service port: **low**
- Recreating Route: **low** (brief DNS TTL gap)
- Restarting Router: **high** — affects all Routes in the cluster

---

## Follow-up Actions
1. After fix: `curl -I https://<route-hostname>` — confirm 200 OK.
2. Check TLS certificate expiry: `echo | openssl s_client -connect <hostname>:443 2>/dev/null | openssl x509 -noout -dates`
3. Set up monitoring on Router metrics: `haproxy_backend_status` in Prometheus.
