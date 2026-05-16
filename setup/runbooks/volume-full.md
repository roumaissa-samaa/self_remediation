---
type: kubernetes
agent: Platform
---

# Runbook — Volume Full / No Space Left on Device

**Symptom**: The application can no longer write to disk — logs stop, database writes fail, or the process crashes.
**Indicators**: `No space left on device` in application logs, `df -h` inside pod shows 100% usage, pod may restart with exit code 1.

---

## Common Causes

1. **PVC undersized** — the volume was provisioned too small for actual data growth.
2. **Log accumulation** — application logs written to the volume without rotation or TTL.
3. **Temp files not cleaned** — batch jobs or upload handlers leave large temp files in `/tmp` or `/data`.
4. **Database growth** — PostgreSQL/MySQL WAL logs or unvacuumed tables consuming all space.
5. **emptyDir saturation** — a shared in-pod scratch volume filled by a sidecar or init container.

---

## Diagnosis Steps

```bash
# Step 1 — Check disk usage inside the pod
oc exec -it <pod-name> -n <namespace> -- df -h

# Step 2 — Find the largest files/directories
oc exec -it <pod-name> -n <namespace> -- du -sh /* 2>/dev/null | sort -rh | head -20
oc exec -it <pod-name> -n <namespace> -- du -sh /var/log/* 2>/dev/null | sort -rh | head -10

# Step 3 — Check PVC status and capacity
oc get pvc -n <namespace>
oc describe pvc <pvc-name> -n <namespace>

# Step 4 — Check if StorageClass supports volume expansion
oc get storageclass <sc-name> -o jsonpath='{.allowVolumeExpansion}'
```

---

## Remediation

### Immediate — clean up large files inside the pod
```bash
# Delete old log files (adjust path)
oc exec -it <pod-name> -n <namespace> -- find /var/log -name "*.log" -mtime +7 -delete

# Truncate a log file without deleting it (safer for open file handles)
oc exec -it <pod-name> -n <namespace> -- truncate -s 0 /var/log/app/app.log
```

### Expand the PVC (if StorageClass allows it)
```bash
# Edit the PVC to request more storage
oc patch pvc <pvc-name> -n <namespace> \
  -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'

# Verify expansion is in progress
oc describe pvc <pvc-name> -n <namespace>
# Look for: "Resizing" condition or updated capacity
```
> On OpenShift with ODF/Ceph, expansion is immediate. On some providers it requires a pod restart.

### Increase emptyDir limit on the Deployment
```bash
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/volumes/0/emptyDir","value":{"sizeLimit":"5Gi"}}]'
```

### Long-term — redirect logs to external system
Configure the application to send logs to stdout/stderr (collected by the cluster log aggregator) instead of writing to a volume. On OpenShift, use the OpenShift Logging stack (Loki / Elasticsearch).

---

## Risk Level
- Deleting old log files: **low**
- Expanding PVC: **low** (no downtime required on most StorageClasses)
- Truncating active log files: **medium** (brief log gap)

---

## Follow-up Actions
1. After cleanup: `oc exec <pod-name> -n <namespace> -- df -h` — confirm free space.
2. Set `resources.limits.ephemeralStorage` on the container to prevent emptyDir abuse.
3. Add a Prometheus alert: `kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85`.
4. Configure log rotation in the application (logrotate, rolling file appender).
