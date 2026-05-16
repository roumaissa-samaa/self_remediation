---
type: kubernetes
agent: Platform
---

# Runbook — Helm Release Failed / Rollback

**Symptom**: A Helm install or upgrade did not complete successfully. The release is stuck in a broken state.
**Indicators**: `helm list` shows status `failed` or `pending-install`/`pending-upgrade`, pods from the chart are in error state.

---

## Helm Release States

| Status | Meaning |
|--------|---------|
| `deployed` | Last operation succeeded |
| `failed` | Last operation failed |
| `pending-install` | Install started but not finished (timed out or interrupted) |
| `pending-upgrade` | Upgrade started but not finished |
| `superseded` | This revision was replaced by a newer one |

---

## Common Causes

1. **Template rendering error** — invalid `values.yaml` or template syntax error (Go template).
2. **Missing dependency** — a required sub-chart was not downloaded (`helm dependency update` not run).
3. **Resource conflict** — a resource from a previous release or manual creation already exists (`already exists` error).
4. **`--wait` timeout** — Helm waited for pods to become ready but they didn't start in time.
5. **RBAC — Helm operator lacks permissions** — the deploying ServiceAccount cannot create the required resources.
6. **Hook failure** — a pre-install or post-upgrade Helm hook job failed.

---

## Diagnosis Steps

```bash
# Step 1 — Check release status and last error
helm status <release-name> -n <namespace>
helm history <release-name> -n <namespace>

# Step 2 — Get the manifests that were applied (last revision)
helm get manifest <release-name> -n <namespace> | head -100

# Step 3 — Check pods created by the chart
oc get pods -n <namespace> -l app.kubernetes.io/instance=<release-name>
oc describe pod <pod-name> -n <namespace>

# Step 4 — Validate chart templates without deploying
helm template <release-name> <chart-path> -f values.yaml | oc apply --dry-run=client -f -

# Step 5 — Check for resource conflicts
helm get manifest <release-name> -n <namespace> | grep "name:" | \
  xargs -I{} oc get {} -n <namespace> 2>&1 | grep -v "not found"
```

---

## Remediation

### Rollback to the last successful revision
```bash
# View history to find the last good revision
helm history <release-name> -n <namespace>

# Rollback to previous revision
helm rollback <release-name> -n <namespace>

# Rollback to a specific revision number
helm rollback <release-name> <revision-number> -n <namespace>

# Confirm rollback
helm status <release-name> -n <namespace>
```

### Fix `pending-install` stuck state — delete and reinstall
```bash
# If Helm is stuck in pending-install, force delete the broken release
helm delete <release-name> -n <namespace> --no-hooks

# If resources were partially created, clean them up
oc delete all -l app.kubernetes.io/instance=<release-name> -n <namespace>

# Reinstall
helm install <release-name> <chart> -f values.yaml -n <namespace>
```

### Fix resource conflict (`already exists` error)
```bash
# Option A — adopt the existing resource into the Helm release
oc annotate <resource-type> <resource-name> -n <namespace> \
  meta.helm.sh/release-name=<release-name> \
  meta.helm.sh/release-namespace=<namespace>
oc label <resource-type> <resource-name> -n <namespace> \
  app.kubernetes.io/managed-by=Helm

# Option B — delete the conflicting resource and re-run helm upgrade
oc delete <resource-type> <resource-name> -n <namespace>
helm upgrade <release-name> <chart> -f values.yaml -n <namespace>
```

### Test values before applying
```bash
# Dry-run the upgrade
helm upgrade <release-name> <chart> -f values.yaml -n <namespace> \
  --dry-run --debug 2>&1 | head -100

# Lint the chart
helm lint <chart-path> -f values.yaml
```

---

## Risk Level
- `helm rollback`: **medium** — reverts all chart resources to a previous state
- Force delete and reinstall: **high** — brief downtime for the application
- Annotating resources to adopt them: **low**

---

## Follow-up Actions
1. After rollback: `helm status <release-name> -n <namespace>` — confirm status is `deployed`.
2. Check pods are healthy: `oc get pods -n <namespace> -l app.kubernetes.io/instance=<release-name>`.
3. Identify the root cause in the `values.yaml` or chart templates before re-attempting the upgrade.
4. Use `--atomic` flag in CI/CD: `helm upgrade --atomic --timeout 5m` — automatically rolls back on failure.
