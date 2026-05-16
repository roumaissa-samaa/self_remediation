---
type: ci-cd
agent: Integration
---

# Runbook — Jenkins Build Timeout & Queue Stuck

**Symptom**: Jobs stay in **queue** for a long time, or a running build **hangs** until the global or stage timeout kills it.

**Indicators**:
- Build shows `Queued` or `Waiting for next available executor`.
- Console stops progressing on one step for many minutes.
- Log ends with `Timeout` or `Aborted` after `timeout(...) { }` in Jenkinsfile.

---

## Common Causes

1. **No idle executors** — all agents busy; executor count too low.
2. **Blocked stage** — waiting for input (`input` step), lock (`lock` resource), or `waitUntil` condition never true.
3. **Deadlock** — two jobs hold `lock` on same resource in opposite order.
4. **Hung process** — test runner, Docker build, or `kubectl rollout status` stuck.
5. **Infrastructure** — agent lost contact with controller; cloud VM not provisioned.

---

## Diagnosis Steps

1. Open the job → **Build Queue** — note position and reason (label, throttle).
2. Open running build → **Thread dump** (if available) or **Pause/resume** overlay for **input** steps.
3. **Manage Jenkins → Nodes** — check executors in use vs idle.
4. Search Jenkinsfile for: `timeout`, `waitUntil`, `lock`, `milestone`, `input`.
5. On the agent host (if you have access): `top`, `df -h`, `docker ps`, stuck `git` or `java` processes.

```bash
# Example: rollout stuck (from pipeline log)
kubectl rollout status deployment/<name> -n <namespace> --timeout=60s
kubectl get pods -n <namespace> -w
```

---

## Remediation

### Queue: no matching agent
- Add capacity (more agents / higher cloud max instances).
- Relax label requirements temporarily only if security allows.
- Cancel duplicate builds that consume executors (`Abort old builds` strategy).

### Hang: explicit input / approval
- Complete or abort the **input** step in UI; document who must approve.

### Hang: lock contention
- Identify lock resource name; cancel lower-priority job holding the lock.
- Redesign pipeline to shorten lock scope (smaller critical section).

### Hang: rollout or external wait
- Fix underlying cluster or service (see K8s runbooks); do not only increase timeout without fixing root cause.

### Timeout too aggressive
- After root cause is fixed, adjust `timeout` values for slow but healthy steps (e.g. large integration suite).

---

## Risk Level

- Aborting stuck build: **low**
- Raising timeouts without investigation: **medium** (masks real issues)
- Force-unlocking shared resources: **medium** (coordinate with team)

---

## Follow-up Actions

1. Enable **build discarder** and **concurrent build** limits where appropriate.
2. Add **timestamps** in console and structured logging for long steps.
3. For cloud agents: verify provisioning logs and IAM/network to controller.
