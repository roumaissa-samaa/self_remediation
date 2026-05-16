---
type: ci-cd
agent: Integration
---

# Runbook — Jenkins Pipeline Failed

**Symptom**: A Jenkins pipeline job ends with `FAILURE`, `ABORTED`, or `UNSTABLE` and does not deploy or verify as expected.

**Indicators**:
- Build console shows red status or failed stage.
- Downstream deploy job did not run or was skipped.
- Notifications (email/Slack) report failure on a specific stage (build, test, deploy).

---

## Common Causes

1. **Compile/test failure** — bad commit, missing dependency, flaky test.
2. **Infrastructure** — agent offline, disk full on agent, wrong label / no executor.
3. **Credentials / secrets** — expired token, wrong vault path, missing `withCredentials` binding.
4. **External dependency** — artifact repo down, npm/PyPI timeout, Docker registry 401/403.
5. **Deployment blocked** — target cluster/API unreachable; previous deployment still rolling; approval gate not met.
6. **Shared state with K8s** — deploy stage waits for pods that are `CrashLoopBackOff` or not ready.

---

## Diagnosis Steps

```groovy
// In Jenkins UI: open the failed build → Console Output
// Note: first failed stage and exact error line (stack trace, HTTP code, kubectl/oc exit code).
```

```bash
# If deploy uses kubectl/oc from Jenkins agent:
# Re-run the failing command on the agent or a bastion with same kubeconfig
kubectl config current-context
kubectl get pods -n <namespace> -l app=<service>
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace> --tail=200

# Jenkins CLI (optional) — list last builds
# java -jar jenkins-cli.jar -s $JENKINS_URL get-job <job-name>
```

**Checklist**:
- Which stage failed first (Checkout → Build → Test → Scan → Deploy)?
- Is the error **deterministic** (same commit always fails) or **intermittent**?
- Did **agent** change (new image, dependency cache cleared)?
- Any **quota/rate limit** from registry or API?

---

## Remediation by Cause

### Cause: Transient network / registry timeout
- Re-trigger the pipeline from the same commit (`Build Now` or `rebuild` API).
- If using retry wrapper in Jenkinsfile, increase retries only for known-idempotent steps.

### Cause: Bad commit or broken tests
- Fix code or skip broken test only with team agreement; prefer revert of offending commit for `main`/`master`.

### Cause: Agent offline or wrong label
- In Jenkins: **Manage Jenkins → Nodes** — bring agent online or fix cloud template.
- Fix pipeline `agent { label '...' }` to match available capacity.

### Cause: Credentials expired
- Rotate secret in credential store or vault; update job to use new ID.
- Re-run pipeline after validation with a small test job.

### Cause: Deploy blocked by unhealthy K8s workload
- Follow cluster runbooks (`crashloopbackoff.md`, `deployment-stuck.md`) until workload is healthy; then re-run deploy stage or full pipeline.

### Cause: DB or API dependency timeout during integration tests
- See `db-connection-pool-exhausted.md` and `db-instance-unreachable.md`.
- Confirm connection strings and pool sizes for the environment used by CI.

---

## Risk Level

- Re-trigger build: **low**
- Changing credentials or production deploy parameters: **medium**
- Force deploy while cluster unhealthy: **high**

---

## Follow-up Actions

1. Capture console log snippet and failed stage in ticket.
2. Add or tighten health checks before deploy stage (smoke test, canary).
3. For flaky tests: quarantine or fix; do not mask with unlimited retries on deploy.
