---
type: kubernetes
agent: Platform
---

# Runbook — Volume Mount Error / MountVolume Failed

**Symptom**: A pod is stuck in `ContainerCreating` and never starts because a volume cannot be attached or mounted.
**Indicators**: Events show `MountVolume.SetUp failed`, `FailedMount`, `Unable to attach or mount volumes`, `timed out waiting for the condition`.

---

## Common Causes

1. **RWO volume already attached to another node** — a `ReadWriteOnce` PVC can only be mounted on one node at a time; if the old pod was not fully terminated, the volume is still claimed.
2. **CSI driver pod crashed** — the Container Storage Interface driver (e.g., `csi-cephfs`, `aws-ebs-csi`) is not running.
3. **NFS permissions error** — the NFS server rejects the mount request due to IP/UID mismatch.
4. **ConfigMap or Secret referenced as volume does not exist** — see runbook `02_config_errors.md`.
5. **Node lacks access to the storage backend** — network firewall, IAM policy, or storage credentials blocking access from the node.
6. **Volume stuck in `Terminating`** — previous pod termination incomplete; volume detach is pending.

---

## Diagnosis Steps

```bash
# Step 1 — Read the exact mount error
oc describe pod <pod-name> -n <namespace>
# Look for: Events with "MountVolume.SetUp failed for volume ..."
# The message will tell you: NFS error, CSI error, multi-attach error, etc.

# Step 2 — Check PVC and PV status
oc get pvc -n <namespace>
oc describe pvc <pvc-name> -n <namespace>
oc describe pv <pv-name>

# Step 3 — Check CSI driver pods
oc get pods -n openshift-cluster-csi-drivers
oc get pods -n kube-system | grep csi

# Step 4 — Check if another pod is using the same RWO volume
oc get pods --all-namespaces -o json | \
  python3 -c "
import sys, json
pods = json.load(sys.stdin)['items']
for p in pods:
  for v in p['spec'].get('volumes', []):
    if v.get('persistentVolumeClaim', {}).get('claimName') == '<pvc-name>':
      print(p['metadata']['namespace'], p['metadata']['name'], p['status']['phase'])
"
```

---

## Remediation

### Fix — RWO multi-attach (volume stuck on old node)
```bash
# Force-delete the old pod that still holds the volume
oc delete pod <old-pod-name> -n <namespace> --force --grace-period=0

# Wait for the volume to detach (usually 30-60s), then the new pod will mount it
oc get pod <new-pod-name> -n <namespace> -w
```

### Fix — CSI driver not running
```bash
# Check and restart CSI node pods
oc get pods -n openshift-cluster-csi-drivers
oc rollout restart daemonset/<csi-node-daemonset> -n openshift-cluster-csi-drivers
```

### Fix — NFS permission denied
```bash
# Test NFS mount from inside the node
oc debug node/<node-name>
chroot /host
showmount -e <nfs-server-ip>
mount -t nfs <nfs-server-ip>:<export-path> /mnt/test

# Fix: ensure the NFS export allows the node's IP in /etc/exports on the NFS server
# Example: /data *(rw,sync,no_root_squash)
```

### Fix — ConfigMap or Secret volume missing
```bash
# Check what volumes the pod needs
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.volumes}'

# Create the missing ConfigMap
oc create configmap <cm-name> -n <namespace> --from-literal=key=value

# Create the missing Secret
oc create secret generic <secret-name> -n <namespace> --from-literal=key=value
```

---

## Risk Level
- Force-deleting a pod: **medium** — brief downtime, data in emptyDir is lost
- Restarting CSI DaemonSet: **medium** — may briefly affect storage operations on all nodes
- NFS server changes: **high** — affects all NFS clients

---

## Follow-up Actions
1. After fix: `oc get pod <pod-name> -n <namespace> -w` — confirm pod reaches `Running`.
2. If using RWO volumes with rolling deployments, consider switching to `ReadWriteMany` (ODF CephFS) to avoid multi-attach issues.
3. Set `terminationGracePeriodSeconds: 30` on pods using RWO volumes to ensure clean detach.
