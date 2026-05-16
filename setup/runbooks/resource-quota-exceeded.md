---
type: kubernetes
agent: Platform
---

# Runbook — Resource Quota Exceeded

**Symptom**: Pod or Deployment cannot be created. API returns a `Forbidden` error.
**Indicators**: `Error from server (Forbidden): pods is forbidden: exceeded quota`, Events contain `exceeded quota: compute-resources`.

---

## How ResourceQuota Works

A `ResourceQuota` object limits the total CPU, memory, storage, and object count that can be consumed in a namespace. When a new pod would exceed the quota, the API server rejects the creation request.

---

## Common Causes

1. **Too many pods** — namespace has reached `pods` count limit.
2. **CPU/memory requests too high** — new pod requests push namespace over `requests.cpu` or `requests.memory`.
3. **Missing resource requests on pod** — if quota is set on `requests.cpu`, every pod MUST define `resources.requests.cpu`.
4. **LimitRange conflict** — a `LimitRange` injects default requests, which may push the namespace over quota.

---

## Diagnosis Steps

```bash
# Step 1 — See current quota usage vs limits
oc describe resourcequota -n <namespace>
# Look for lines where "Used" approaches "Hard"

# Step 2 — Get full quota YAML
oc get resourcequota -n <namespace> -o yaml

# Step 3 — Count current pods
oc get pods -n <namespace> --no-headers | wc -l

# Step 4 — Find resource-heavy pods
oc adm top pods -n <namespace> --sort-by=memory
```

---

## Remediation

### Free up resources — scale down unused deployments
```bash
oc scale deployment/<unused-name> --replicas=0 -n <namespace>
```

### Free up resources — delete completed/failed pods
```bash
oc delete pods --field-selector=status.phase=Failed -n <namespace>
oc delete pods --field-selector=status.phase=Succeeded -n <namespace>
```

### Reduce pod resource requests (if over-provisioned)
```bash
oc patch deployment/<name> -n <namespace> \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container>","resources":{"requests":{"cpu":"50m","memory":"64Mi"}}}]}}}}'
```

### Request quota increase (requires cluster-admin)
```bash
oc patch resourcequota <quota-name> -n <namespace> \
  -p '{"spec":{"hard":{"pods":"20","requests.cpu":"8","requests.memory":"16Gi","limits.cpu":"16","limits.memory":"32Gi"}}}'
```

---

## Risk Level
- Scaling down unused deployments: **low**
- Deleting completed pods: **low**
- Increasing quota: **medium** — requires cluster-admin approval in enterprise

---

## Follow-up Actions
1. Set up alerts on quota usage > 80%: use Prometheus `kube_resourcequota` metric.
2. Review `LimitRange` in the namespace — it may be injecting large default requests.
3. Consider `VerticalPodAutoscaler` in recommendation mode to right-size requests automatically.
