---
type: kubernetes
agent: Platform
---

# Runbook — Pod Pending / Cannot Be Scheduled

**Symptom**: A pod is created but stays in `Pending` state indefinitely and is never assigned to a node.
**Indicators**: `STATUS: Pending` in `oc get pods`, Events show `0/N nodes are available`, no node assigned in `NODE` column.

---

## Scheduling Process

The Kubernetes scheduler filters nodes in two phases:
1. **Filter** — eliminates nodes that don't meet hard constraints (resources, taints, affinity).
2. **Score** — ranks remaining nodes by soft preferences.

If no node passes the filter phase, the pod stays Pending.

---

## Common Causes

1. **Insufficient CPU/memory** — no node has enough allocatable resources to fit the pod's `requests`.
2. **NodeSelector or nodeAffinity** — the pod requires a node label that no node has.
3. **Taint without matching Toleration** — all nodes have a taint the pod doesn't tolerate.
4. **PVC not bound** — pod is waiting for a PVC to become `Bound` (see `pvc-not-bound.md`).
5. **Resource Quota exceeded** — the namespace quota prevents creating more pods (see `resource-quota-exceeded.md`).
6. **Topology spread constraints** — the spread constraint cannot be satisfied with available nodes.
7. **Pod affinity/anti-affinity** — requiredDuringScheduling rule cannot be met.

---

## Diagnosis Steps

```bash
# Step 1 — Read the exact scheduling failure reason
oc describe pod <pod-name> -n <namespace>
# Look for Events like:
#   "0/3 nodes are available: 3 Insufficient cpu"
#   "0/3 nodes are available: 3 node(s) had taint {key:value}, that the pod didn't tolerate"
#   "0/3 nodes are available: 3 node(s) didn't match node selector"

# Step 2 — Check node resource availability
oc adm top nodes
oc describe nodes | grep -A5 "Allocated resources"

# Step 3 — Check node labels (for nodeSelector issues)
oc get nodes --show-labels

# Step 4 — Check node taints
oc get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Step 5 — Check namespace quota
oc describe resourcequota -n <namespace>
```

---

## Remediation

### Fix A — Insufficient resources: reduce pod requests
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container>","resources":{"requests":{"cpu":"50m","memory":"64Mi"}}}]}}}}'
```

### Fix B — NodeSelector mismatch: remove or fix the selector
```bash
# View current nodeSelector
oc get deployment/<deployment-name> -n <namespace> \
  -o jsonpath='{.spec.template.spec.nodeSelector}'

# Remove the nodeSelector entirely
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"remove","path":"/spec/template/spec/nodeSelector"}]'

# Or add the required label to a node (cluster-admin required)
oc label node <node-name> <key>=<value>
```

### Fix C — Taint without Toleration: add toleration to the pod
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  -p '{"spec":{"template":{"spec":{"tolerations":[{"key":"<taint-key>","operator":"Exists","effect":"NoSchedule"}]}}}}'
```

### Fix D — PVC not bound
See runbook `pvc-not-bound.md`.

### Fix E — Resource Quota exceeded
See runbook `resource-quota-exceeded.md`.

### Fix F — Add more capacity (cluster-admin)
```bash
# On OpenShift with MachineAutoscaler:
oc get machineautoscaler -n openshift-machine-api

# Manually scale a MachineSet:
oc scale machineset/<machineset-name> --replicas=3 -n openshift-machine-api
```

---

## Risk Level
- Reducing resource requests: **low** (may affect app performance if undersized)
- Removing nodeSelector: **low** to **medium** depending on workload
- Adding node labels: **low**
- Scaling MachineSet: **medium** (adds cloud cost)

---

## Follow-up Actions
1. After fix: `oc get pod <pod-name> -n <namespace> -w` — watch for transition from `Pending` to `Running`.
2. If the pod remains Pending after 5 minutes, re-run `oc describe pod` — the reason may have changed.
3. Review cluster-wide node utilization: `oc adm top nodes` — if all nodes are >80% allocated, plan capacity increase.
