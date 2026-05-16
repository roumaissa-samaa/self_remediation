---
type: kubernetes
agent: Platform
---

# Runbook — Deployment Stuck / Rollout Stalled

**Symptom**: A new deployment is not progressing — old pods remain running and new pods are not replacing them.
**Indicators**: `oc rollout status deployment/<name>` hangs with "Waiting for rollout to finish", `AVAILABLE` count does not increase.

---

## How Rolling Updates Work

By default, `RollingUpdate` strategy creates new pods before terminating old ones. It respects `maxUnavailable` and `maxSurge` settings. If new pods fail to become Ready, the rollout pauses to avoid taking down all old pods.

---

## Common Causes

1. **New pods CrashLoopBackOff** — the new image or config is broken; new pods never reach Ready.
2. **New pods stuck in Pending** — resource quota or node capacity prevents scheduling the surge pods.
3. **Readiness probe failure** — new pods start but never pass readiness, so old pods are not terminated.
4. **ImagePullBackOff on new image** — wrong tag or registry credentials missing.
5. **PodDisruptionBudget (PDB)** — a PDB prevents terminating old pods below `minAvailable`.
6. **Deadline exceeded** — `progressDeadlineSeconds` (default 600s) expired.

---

## Diagnosis Steps

```bash
# Step 1 — Check rollout status
oc rollout status deployment/<deployment-name> -n <namespace>

# Step 2 — See deployment conditions
oc describe deployment <deployment-name> -n <namespace>
# Look for: Progressing=False, ReplicaFailure=True

# Step 3 — Identify new vs old pods
oc get pods -n <namespace> -o wide
# New pods belong to the latest ReplicaSet

# Step 4 — Check new pods for errors
oc describe pod <new-pod-name> -n <namespace>
oc logs <new-pod-name> -n <namespace> --previous

# Step 5 — Check PodDisruptionBudgets
oc get pdb -n <namespace>
oc describe pdb <pdb-name> -n <namespace>
```

---

## Remediation

### Rollback to previous working revision
```bash
# View rollout history
oc rollout history deployment/<deployment-name> -n <namespace>

# Rollback to immediately previous revision
oc rollout undo deployment/<deployment-name> -n <namespace>

# Rollback to a specific revision number
oc rollout undo deployment/<deployment-name> -n <namespace> --to-revision=<N>

# Confirm rollback is progressing
oc rollout status deployment/<deployment-name> -n <namespace>
```

### Force a Recreate rollout (downtime, but clears stuck state)
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  -p '{"spec":{"strategy":{"type":"Recreate"}}}'
oc rollout restart deployment/<deployment-name> -n <namespace>
```

### Fix new pods failing — patch image back to last known good
```bash
oc set image deployment/<deployment-name> \
  <container-name>=<registry>/<image>:<last-good-tag> \
  -n <namespace>
```

### Pause and resume rollout (to investigate without aborting)
```bash
oc rollout pause deployment/<deployment-name> -n <namespace>
# ... investigate new pods ...
oc rollout resume deployment/<deployment-name> -n <namespace>
```

---

## Risk Level
- `oc rollout undo`: **medium** — reverts code changes, brief traffic interruption during transition
- `Recreate` strategy: **high** — full downtime between old and new pods
- Patching image: **low** if reverting to known-good tag

---

## Follow-up Actions
1. After rollback: identify root cause in the failing image/config before re-deploying.
2. Review `progressDeadlineSeconds` — default 600s may be too short for slow-starting apps.
3. Consider adding a `startupProbe` to prevent readiness failures during initialization.
4. Use `oc rollout history --revision=<N> deployment/<name> -n <ns>` to see what changed between revisions.
