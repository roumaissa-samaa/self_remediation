---
type: kubernetes
agent: Platform
---

# Runbook — PersistentVolumeClaim (PVC) Not Bound

**Symptom**: A pod stays in `Pending` because its volume claim cannot be satisfied.
**Indicators**: `oc get pvc` shows `STATUS: Pending`, pod Events show `pod has unbound immediate PersistentVolumeClaims`.

---

## PVC Binding Process

1. A PVC is created with a `storageClassName`, `accessModes`, and `resources.requests.storage`.
2. The PersistentVolume controller looks for a matching PV, or triggers the StorageClass provisioner to create one dynamically.
3. If no match is found, the PVC stays `Pending` and the pod cannot start.

---

## Common Causes

1. **StorageClass does not exist** — the `storageClassName` in the PVC is misspelled or the class was deleted.
2. **No dynamic provisioner** — the StorageClass exists but has no provisioner (or the provisioner pod is down).
3. **Access mode incompatible** — PVC requests `ReadWriteMany` but the storage backend only supports `ReadWriteOnce`.
4. **Storage quota exceeded** — namespace has a `ResourceQuota` on storage that is full.
5. **No PV with matching size** — static PV exists but with a smaller capacity than the PVC requests.
6. **VolumeBindingMode: WaitForFirstConsumer** — binding is delayed until a pod is scheduled; pod is Pending because PVC is Pending (circular).

---

## Diagnosis Steps

```bash
# Step 1 — Check PVC status and events
oc describe pvc <pvc-name> -n <namespace>
# Look for: Events with "ProvisioningFailed", "no storage class found", "no persistent volumes available"

# Step 2 — Verify the StorageClass exists
oc get storageclass
oc describe storageclass <sc-name>

# Step 3 — Check if dynamic provisioner is running
oc get pods -n openshift-cluster-storage-operator
oc get pods -n kube-system | grep provisioner

# Step 4 — List available PVs (for static binding)
oc get pv
oc describe pv <pv-name>  # Check storageClassName, accessModes, capacity

# Step 5 — Check storage quota
oc describe resourcequota -n <namespace> | grep storage
```

---

## Remediation

### Fix — use the correct StorageClass
```bash
# List available StorageClasses
oc get storageclass

# Patch the PVC (only works if PVC was never bound)
# → Usually requires deleting and recreating the PVC with the correct storageClassName
oc delete pvc <pvc-name> -n <namespace>
oc apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <pvc-name>
  namespace: <namespace>
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: <correct-storageclass>
  resources:
    requests:
      storage: 10Gi
EOF
```

### Fix — manually create a PV for static binding
```bash
oc apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: my-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  storageClassName: <sc-name>
  hostPath:
    path: /mnt/data   # replace with NFS/CSI path in production
EOF
```

### On OpenShift with ODF (OpenShift Data Foundation)
```bash
# Use the correct ODF StorageClasses:
# Block storage (RWO):   ocs-storagecluster-ceph-rbd
# Shared filesystem (RWX): ocs-storagecluster-cephfs

oc patch pvc <pvc-name> -n <namespace> \
  --type=merge \
  -p '{"spec":{"storageClassName":"ocs-storagecluster-ceph-rbd"}}'
```

---

## Risk Level
- Deleting and recreating a PVC: **high** — all data on the old PVC is permanently lost
- Creating a PV manually: **low**
- Patching StorageClass name: **low** (if PVC was never bound)

---

## Follow-up Actions
1. After fix: `oc get pvc -n <namespace> -w` — watch for STATUS to change to `Bound`.
2. Verify the pod starts: `oc get pods -n <namespace>`.
3. Check `VolumeBindingMode` on the StorageClass — `WaitForFirstConsumer` requires the pod to be scheduled first; use `oc describe storageclass <name>` to confirm.
