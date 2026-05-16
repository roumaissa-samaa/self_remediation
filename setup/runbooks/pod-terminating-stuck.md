---
type: kubernetes
agent: Platform
---

﻿# Runbook — Pod Stuck in Terminating State

**Symptom**: A pod has been in `Terminating` state for more than a few minutes and does not complete deletion.
**Indicators**: `oc get pod` shows `Terminating` with an age of several minutes or hours. `oc delete pod` appears to hang.

---

## How Pod Termination Works

When a pod is deleted, Kubernetes:
1. Sets a `deletionTimestamp` on the pod object.
2. Sends `SIGTERM` to all containers.
3. Waits for `terminationGracePeriodSeconds` (default: 30s).
4. Sends `SIGKILL` if the containers haven't stopped.
5. Removes the pod from the API server once all finalizers are cleared.

A pod gets stuck in `Terminating` when step 4 fails (process ignores SIGKILL) or when **finalizers** are not removed.

---

## Common Causes

1. **Finalizers not cleared** — a controller (e.g., PVC protection, network policy controller) has set a finalizer on the pod and is not removing it.
2. **Volume unmount failure** — a PVC or network filesystem (NFS, CephFS) cannot be cleanly unmounted.
3. **Node is NotReady or unreachable** — the kubelet on the node cannot send SIGKILL because the node is down.
4. **Process ignores SIGTERM and SIGKILL** — rare, usually indicates a kernel-level hang (I/O wait, uninterruptible sleep).
5. **Namespace stuck in Terminating** — the entire namespace is being deleted and a resource has a blocking finalizer.

---

## Diagnosis Steps

```bash
# Step 1 — Check how long the pod has been terminating and its finalizers
oc get pod <pod-name> -n <namespace> -o json | \
  python3 -c "import sys,json; p=json.load(sys.stdin)['metadata']; print('deletionTimestamp:', p.get('deletionTimestamp')); print('finalizers:', p.get('finalizers'))"

# Step 2 — Check the node status
oc get node <node-name>
oc describe node <node-name> | grep -A5 "Conditions"

# Step 3 — Check if there are PVC issues
oc get pvc -n <namespace>
oc describe pvc <pvc-name> -n <namespace>

# Step 4 — Check events on the pod
oc get events -n <namespace> \
  --field-selector involvedObject.name=<pod-name> \
  --sort-by=.lastTimestamp

# Step 5 — Check if the namespace itself is terminating
oc get namespace <namespace>
```

---

## Remediation

### Force delete the pod (most common fix)
```bash
oc delete pod <pod-name> -n <namespace> --grace-period=0 --force
```
> This bypasses the grace period and forces immediate deletion from the API server. Use when the node is healthy and the pod is just stuck.

### Remove a blocking finalizer manually
```bash
# Remove the finalizer by patching the pod metadata
oc patch pod <pod-name> -n <namespace> \
  -p '{"metadata":{"finalizers":null}}' \
  --type=merge
```
> Warning: Only do this if you understand why the finalizer was set. Removing it may leave orphaned resources (e.g., unreleased PVCs).

### Node is NotReady — the pod will self-clean when node recovers
```bash
# Check node status
oc get nodes
oc describe node <node-name>

# If the node is permanently gone, delete the node object
oc delete node <node-name>
# Kubernetes will then force-delete all pods that were on that node.
```

### Namespace stuck in Terminating — remove blocking finalizers
```bash
# List all resources blocking namespace deletion
oc api-resources --verbs=list --namespaced -o name | \
  xargs -I{} oc get {} -n <namespace> --ignore-not-found 2>/dev/null

# Patch namespace to remove finalizers
oc patch namespace <namespace> \
  -p '{"spec":{"finalizers":[]}}' \
  --type=merge
```

---

## Risk Level
- Force deleting a pod (`--grace-period=0 --force`): **medium** — skips graceful shutdown, may cause data loss if the pod was writing to a database or file system
- Removing finalizers: **medium** — may leave orphaned resources
- Deleting a node object: **high** — removes the node from the cluster permanently

---

## Follow-up Actions
1. After force delete: confirm the pod is gone — `oc get pod <pod-name> -n <namespace>` should return `NotFound`.
2. Check that the PVC associated with the pod is still healthy: `oc get pvc -n <namespace>`.
3. If the node was NotReady, investigate the node's health before rescheduling workloads onto it.
4. Review why the pod got stuck to prevent recurrence (check application shutdown handlers, PVC cleanup logic).
