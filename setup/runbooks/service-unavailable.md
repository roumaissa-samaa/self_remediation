---
type: kubernetes
agent: Platform
---

# Runbook — Service Unavailable (503 / No Endpoints)

**Symptom**: Requests to a Kubernetes Service fail with 503 or "connection refused". The application is not receiving traffic.
**Indicators**: `oc get endpoints <service>` shows `(none)` or no addresses, 503 from Ingress/Route, application logs show no incoming requests.

---

## How a Service Routes Traffic

`Client → Service (ClusterIP) → Endpoints → Pod`

The `Endpoints` object is automatically populated with the IP of every pod that:
1. Matches the Service's `spec.selector` labels
2. Has passed its readiness probe

If either condition fails, the endpoint list is empty and the Service has no backend.

---

## Common Causes

1. **No ready pods** — all pods are Pending, CrashLoopBackOff, or failing the readiness probe.
2. **Service selector mismatch** — `spec.selector` labels don't match any pod's labels.
3. **Service targets wrong port** — `targetPort` doesn't match the port the container actually listens on.
4. **Application not listening on `0.0.0.0`** — app binds to `127.0.0.1` and is unreachable from the Service.
5. **Namespace mismatch** — the Service and the pods are in different namespaces.
6. **NetworkPolicy blocking traffic** — see runbook `networkpolicy-blocking.md`.

---

## Diagnosis Steps

```bash
# Step 1 — Check endpoints (most important step)
oc get endpoints <service-name> -n <namespace>
# "(none)" = the Service has no backend pods

# Step 2 — Compare Service selector vs pod labels
oc get service <service-name> -n <namespace> -o jsonpath='{.spec.selector}'
oc get pods -n <namespace> --show-labels
# The Service selector keys/values must be a SUBSET of the pod's labels

# Step 3 — Check Service port configuration
oc get service <service-name> -n <namespace> -o yaml
# Verify: spec.ports[].targetPort matches containerPort in the pod spec

# Step 4 — Check pod readiness
oc get pods -n <namespace>
oc describe pod <pod-name> -n <namespace>
# Look for: "Readiness probe failed"

# Step 5 — Test direct pod connectivity (bypassing the Service)
POD_IP=$(oc get pod <pod-name> -n <namespace> -o jsonpath='{.status.podIP}')
oc run nettest --image=curlimages/curl --restart=Never --rm -it -n <namespace> \
  -- curl -v http://$POD_IP:<port>/healthz
```

---

## Remediation

### Fix — Service selector mismatch
```bash
# Get the actual pod labels
oc get pod <pod-name> -n <namespace> --show-labels

# Patch the Service selector to match
oc patch service/<service-name> -n <namespace> \
  -p '{"spec":{"selector":{"app":"<correct-label-value>"}}}'

# Verify endpoints are now populated
oc get endpoints <service-name> -n <namespace>
```

### Fix — wrong targetPort
```bash
# Check what port the container actually exposes
oc get pod <pod-name> -n <namespace> \
  -o jsonpath='{.spec.containers[0].ports}'

# Patch the Service with the correct targetPort
oc patch service/<service-name> -n <namespace> \
  -p '{"spec":{"ports":[{"port":80,"targetPort":8080,"protocol":"TCP"}]}}'
```

### Fix — pods not ready (readiness probe failing)
```bash
# Remove readiness probe temporarily to restore traffic
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"remove","path":"/spec/template/spec/containers/0/readinessProbe"}]'
```
> See `pod-not-ready.md` for proper readiness probe fix.

### Fix — scale up to have at least one ready pod
```bash
oc scale deployment/<deployment-name> --replicas=2 -n <namespace>
```

---

## Risk Level
- Patching Service selector or port: **low**
- Removing readiness probe: **medium** — may send traffic to unhealthy pods
- Scaling up replicas: **low**

---

## Follow-up Actions
1. After fix: `oc get endpoints <service-name> -n <namespace>` — confirm pod IPs are listed.
2. End-to-end test: `curl -o /dev/null -s -w "%{http_code}" http://<service>.<namespace>.svc.cluster.local:<port>/`
3. Set up a synthetic health check on the Service URL.
4. Review pod anti-affinity rules — ensure replicas are spread across nodes to avoid single-node failure wiping all endpoints.
