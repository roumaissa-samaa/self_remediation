---
type: kubernetes
agent: Platform
---

# Runbook — Node DiskPressure

**Symptom**: The node starts evicting pods and refusing to schedule new ones due to low disk space.
**Indicators**: `oc describe node <name>` shows `DiskPressure: True`, pods on the node are evicted with message "The node was low on resource: ephemeral-storage".

---

## DiskPressure Thresholds (kubelet defaults)

| Threshold | Default | Effect |
|-----------|---------|--------|
| `imagefs.available < 15%` | Soft eviction after grace period | Pods with no `requests.ephemeral-storage` are evicted |
| `imagefs.available < 10%` | Hard eviction immediately | Pods evicted without grace period |
| `nodefs.available < 10%` | Hard eviction | Same as above |

---

## Common Causes

1. **Container images accumulating** — old/unused images from previous deployments not cleaned up by garbage collection.
2. **Pod logs growing unbounded** — containers writing large volumes to stdout/stderr, filling `/var/log/pods`.
3. **`emptyDir` volumes** — pods writing large amounts of temporary data to `emptyDir`.
4. **Application writing to the container layer** — app writes to the container's writable layer instead of a mounted volume.
5. **Core dumps** — a crashing application writing core dump files to the node filesystem.
6. **etcd or container runtime data** — on control plane nodes, etcd or CRI-O data directories filling up.

---

## Diagnosis Steps

```bash
# Step 1 — Confirm DiskPressure condition
oc describe node <node-name>
# Look for: Conditions — DiskPressure: True

# Step 2 — Access the node and check disk usage
oc debug node/<node-name>
chroot /host

df -h                                          # overall filesystem usage
du -sh /var/lib/containers/storage/* 2>/dev/null | sort -rh | head -10   # images
du -sh /var/log/pods/* 2>/dev/null | sort -rh | head -10                  # pod logs
du -sh /var/lib/kubelet/pods/* 2>/dev/null | sort -rh | head -10          # pod volumes

# Step 3 — Count unused container images
crictl images | wc -l
crictl images   # look for images with no name (dangling)

# Step 4 — Check which pods are using the most ephemeral storage
oc get pods --all-namespaces \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName' \
  --field-selector spec.nodeName=<node-name>
```

---

## Remediation

### Immediate — prune unused container images
```bash
oc debug node/<node-name>
chroot /host

# Remove all unused images (images not referenced by any container)
crictl rmi --prune

# Remove specific dangling images
crictl images | grep '<none>' | awk '{print $3}' | xargs crictl rmi
```

### Clean up old pod logs
```bash
oc debug node/<node-name>
chroot /host

# Remove logs of terminated pods (safe to delete)
find /var/log/pods -name "*.log" -mtime +3 -delete
find /var/log/pods -name "*.log.gz" -mtime +1 -delete
```

### Remove stopped containers
```bash
oc debug node/<node-name>
chroot /host
crictl rm $(crictl ps -a -q --state exited) 2>/dev/null || true
```

### Increase image garbage collection aggressiveness (cluster-admin)
```bash
# OpenShift: patch the kubelet config via MachineConfig
# Or adjust via KubeletConfig:
oc apply -f - <<EOF
apiVersion: machineconfiguration.openshift.io/v1
kind: KubeletConfig
metadata:
  name: gc-config
spec:
  machineConfigPoolSelector:
    matchLabels:
      pools.operator.machineconfiguration.openshift.io/worker: ""
  kubeletConfig:
    imageGCHighThresholdPercent: 80
    imageGCLowThresholdPercent: 70
    evictionHard:
      imagefs.available: "15%"
EOF
```

### Limit pod log size via container runtime configuration
```bash
# OpenShift: set log size limit in ContainerRuntimeConfig
oc apply -f - <<EOF
apiVersion: machineconfiguration.openshift.io/v1
kind: ContainerRuntimeConfig
metadata:
  name: set-log-and-pid-limit
spec:
  machineConfigPoolSelector:
    matchLabels:
      pools.operator.machineconfiguration.openshift.io/worker: ""
  containerRuntimeConfig:
    logSizeMax: "50m"
    logLevel: info
EOF
```

---

## Risk Level
- Pruning unused images: **low** — does not affect running containers
- Deleting old log files: **low**
- Applying KubeletConfig/ContainerRuntimeConfig: **medium** — triggers a rolling node restart via MachineConfig

---

## Follow-up Actions
1. After cleanup: `oc describe node <name>` — confirm `DiskPressure: False`.
2. Cordon the node during cleanup to prevent new pods from being scheduled: `oc adm cordon <node-name>`.
3. Uncordon after: `oc adm uncordon <node-name>`.
4. Set up a Prometheus alert: `node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes < 0.15`.
5. Add `resources.limits.ephemeral-storage` to pods that write large amounts of temporary data.
