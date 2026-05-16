---
type: kubernetes
agent: Platform
---

# Runbook — OpenShift SCC (Security Context Constraints) Violation

**Symptom**: Pod stays in `Pending` or fails to start with a security-related error.
**Indicators**: Events contain `unable to validate against any security context constraint`, `not allowed to run as root`, `container has runAsNonRoot but image has non-numeric user`.

---

## How SCCs Work in OpenShift

OpenShift adds a layer on top of Kubernetes `PodSecurityContext` called **Security Context Constraints (SCCs)**. Every pod must be admitted by at least one SCC, otherwise it is rejected. The default SCC is `restricted`, which disallows root, privilege escalation, and host access.

---

## Common Causes

1. **Image runs as root** — `USER root` or no `USER` directive in Dockerfile.
2. **Non-numeric user in image** — `USER appuser` instead of `USER 1001` (OpenShift requires numeric UIDs).
3. **`allowPrivilegeEscalation: true`** set explicitly or by default.
4. **Mounting `hostPath` volumes** — blocked by `restricted` SCC.
5. **`privileged: true`** container — requires `privileged` SCC.

---

## Diagnosis Steps

```bash
# Step 1 — Check events for SCC rejection message
oc describe pod <pod-name> -n <namespace>

# Step 2 — List SCCs available on the cluster
oc get scc

# Step 3 — Check which SCC the service account can use
oc adm policy who-can use scc anyuid
oc get rolebindings,clusterrolebindings -n <namespace> -o wide | grep <serviceaccount>

# Step 4 — Simulate which SCC would admit the pod
oc adm policy scc-subject-review -f <pod-spec.yaml> -n <namespace>
```

---

## Remediation

### Option 1 — Fix the image (recommended)
Change the Dockerfile to use a numeric non-root UID:
```dockerfile
RUN useradd -u 1001 appuser
USER 1001
```
Use Red Hat UBI base images (`registry.access.redhat.com/ubi9/ubi`) which are SCC-compatible by default.

### Option 2 — Grant `anyuid` SCC to the ServiceAccount
```bash
oc adm policy add-scc-to-user anyuid -z <serviceaccount-name> -n <namespace>
```
> Use only when you cannot modify the image. This allows the pod to run as any UID including root.

### Option 3 — Grant `nonroot` SCC (safer than anyuid)
```bash
oc adm policy add-scc-to-user nonroot -z <serviceaccount-name> -n <namespace>
```
> Allows any non-root UID without requiring a numeric UID in the image.

### Option 4 — Grant `privileged` SCC (last resort, requires cluster-admin)
```bash
oc adm policy add-scc-to-user privileged -z <serviceaccount-name> -n <namespace>
```
> Only for infrastructure components (monitoring agents, CNI plugins, etc.).

---

## Risk Level
- Fixing the image: **low**
- Granting `anyuid`: **medium** — allows root inside container
- Granting `privileged`: **high** — full host access

---

## Follow-up Actions
1. After granting SCC: `oc rollout restart deployment/<name> -n <namespace>`
2. Audit all service accounts with `anyuid`: `oc adm policy who-can use scc anyuid`
3. Consider using OpenShift's built-in SCC `restricted-v2` (OCP 4.11+) for better defaults.
