---
type: kubernetes
agent: Platform
---

# Runbook — Node NotReady

**Symptom**: One or more cluster nodes stop accepting workloads. Pods on the affected node transition to `Unknown` or `Terminating`.
**Indicators**: `oc get nodes` shows `STATUS: NotReady`, kubelet heartbeat stops reaching the control plane.

---

## Node Conditions Reference

| Condition | Normal Value | Meaning when True |
|-----------|-------------|-------------------|
| `Ready` | True | Node is healthy |
| `MemoryPressure` | False | Node is low on memory |
| `DiskPressure` | False | Node is low on disk |
| `PIDPressure` | False | Node is low on process IDs |
| `NetworkUnavailable` | False | Node network is misconfigured |

---

## Common Causes

1. **kubelet service crashed** — the kubelet process on the node stopped or OOMKilled.
2. **Network partition** — the node cannot reach the API server (firewall, NIC failure).
3. **DiskPressure** — the node's root filesystem or container storage is full.
4. **MemoryPressure** — the node is under heavy memory pressure and kubelet cannot function.
5. **Node reboot / OS crash** — the node was restarted unexpectedly.
6. **Certificate expired** — kubelet TLS certificate expired, blocking communication with control plane.

---

## Diagnosis Steps

```bash
# Step 1 — Get node conditions
oc describe node <node-name>
# Look for: Conditions section — which condition is True/False/Unknown

# Step 2 — Check node resource usage
oc adm top nodes

# Step 3 — Check pods running on the affected node
oc get pods --all-namespaces --field-selector spec.nodeName=<node-name>

# Step 4 — Access the node and check kubelet (requires cluster-admin)
oc debug node/<node-name>
chroot /host
systemctl status kubelet
journalctl -u kubelet -n 100 --no-pager

# Step 5 — Check disk usage on the node
oc debug node/<node-name>
chroot /host
df -h
du -sh /var/lib/containers/* 2>/dev/null | sort -rh | head -10
```

---

## Remediation

### Restart kubelet on the node
```bash
oc debug node/<node-name>
chroot /host
systemctl restart kubelet
systemctl status kubelet
```

### Drain the node (evacuate all pods safely)
```bash
# Cordon first — prevents new pods from being scheduled
oc adm cordon <node-name>

# Drain — evicts all pods (respects PodDisruptionBudgets)
oc adm drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=60

# After node is repaired:
oc adm uncordon <node-name>
```

### Free disk space on node (DiskPressure)
```bash
oc debug node/<node-name>
chroot /host
# Remove unused container images
crictl rmi --prune
# Remove stopped containers
crictl rm $(crictl ps -a -q --state exited)
```

### Force-delete Unknown pods stuck on the dead node
```bash
oc delete pods --all-namespaces \
  --field-selector spec.nodeName=<node-name> \
  --force --grace-period=0
```

---

## Risk Level
- Cordoning: **low** — no impact on running workloads
- Draining: **medium** — pods are evicted (PDBs respected, but brief disruption possible)
- Force-deleting pods: **medium** — may cause brief downtime if no replicas exist elsewhere

---

## Follow-up Actions
1. After uncordoning: `oc get nodes` — confirm the node returns to `Ready`.
2. Check why kubelet crashed: `journalctl -u kubelet --since "1 hour ago"` on the node.
3. Set up Prometheus alert: `kube_node_status_condition{condition="Ready",status="false"} == 1`.
4. On OpenShift, use Machine Health Check to automatically replace unhealthy nodes.
