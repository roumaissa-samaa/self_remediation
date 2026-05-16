---
type: kubernetes
agent: Platform
---

# Runbook — Pod Evicted

**Symptom**: A pod is terminated by the kubelet without an application-level crash.
**Indicators**: `STATUS: Evicted` in `oc get pods`, message "The node was low on resource: ..." in `oc describe pod`.

---

## Eviction Types

| Type | Trigger | Who Evicts |
|------|---------|-----------|
| **Soft eviction** | Resource usage crosses a threshold for a grace period | kubelet |
| **Hard eviction** | Resource usage crosses a critical threshold immediately | kubelet |
| **API-initiated** | `oc drain` or PodDisruptionBudget enforcement | API server |
| **Preemption** | High-priority pod needs resources | Scheduler |

---

## Common Causes

1. **Node DiskPressure** — node root filesystem or image storage exceeds the eviction threshold (default 85%).
2. **Node MemoryPressure** — node available memory drops below kubelet's `evictionHard` threshold.
3. **Ephemeral storage limit exceeded** — pod's `resources.limits.ephemeralStorage` exceeded.
4. **`oc adm drain`** — manual or automated node maintenance evicted the pod.
5. **Low-priority pod preempted** — a higher-priority pod needed resources on the same node.

---

## Diagnosis Steps

```bash
# Step 1 — Read the exact eviction reason
oc describe pod <pod-name> -n <namespace>
# Look for: "The node was low on resource: memory/disk/ephemeral-storage"
# Or: "Evicted" with a message field

# Step 2 — Check the node the pod was on
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.nodeName}'
oc describe node <node-name>
# Look for: Conditions — MemoryPressure, DiskPressure

# Step 3 — Check node resource usage at eviction time
oc adm top nodes

# Step 4 — Check if other pods were also evicted on the same node
oc get pods --all-namespaces --field-selector spec.nodeName=<node-name> | grep Evicted
```

---

## Remediation

### Delete evicted pods (they do not auto-delete and clutter the namespace)
```bash
# Delete a single evicted pod
oc delete pod <pod-name> -n <namespace>

# Delete all evicted pods in a namespace
oc get pods -n <namespace> --field-selector=status.phase=Failed \
  -o go-template='{{range .items}}{{if eq .status.reason "Evicted"}}{{.metadata.name}}{{"\n"}}{{end}}{{end}}' \
  | xargs oc delete pod -n <namespace>
```
> Evicted pods from a Deployment are automatically replaced by the ReplicaSet controller.

### Fix DiskPressure on node — see runbook `node-diskpressure.md`

### Fix MemoryPressure — free memory on the node
```bash
# Find memory-heavy pods on the node
oc adm top pods --all-namespaces --sort-by=memory | head -20

# Scale down non-critical workloads
oc scale deployment/<non-critical> --replicas=0 -n <namespace>
```

### Prevent future evictions — set ephemeral storage limits
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container>","resources":{"limits":{"ephemeral-storage":"1Gi"},"requests":{"ephemeral-storage":"500Mi"}}}]}}}}'
```

### Set pod priority to avoid preemption
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  -p '{"spec":{"template":{"spec":{"priorityClassName":"system-cluster-critical"}}}}'
```

---

## Risk Level
- Deleting evicted pods: **low** — they are already terminated
- Scaling down non-critical deployments: **medium**
- Changing priorityClassName: **medium** — affects scheduling decisions cluster-wide

---

## Follow-up Actions
1. Investigate root cause of node pressure — see `node-diskpressure.md` or `node-notready.md`.
2. Add `resources.requests` and `resources.limits` to all containers to improve scheduling accuracy.
3. Enable `PodDisruptionBudget` for critical workloads to control eviction behavior.
4. On OpenShift, review `MachineAutoscaler` — scale up the node pool if the cluster is persistently under memory/disk pressure.
