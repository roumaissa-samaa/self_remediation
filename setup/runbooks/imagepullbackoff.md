---
type: kubernetes
agent: Platform
---

﻿# Runbook — ImagePullBackOff / ErrImagePull

**Symptom**: Kubernetes cannot pull the container image from the registry. The pod stays in `Waiting` state and never starts.
**Indicators**: `Status: ImagePullBackOff` or `ErrImagePull` in `oc get pod`, pull error in events.

---

## Difference Between ErrImagePull and ImagePullBackOff

- **ErrImagePull** — the immediate error on the first pull attempt.
- **ImagePullBackOff** — Kubernetes is backing off retrying after repeated `ErrImagePull` failures.
Both point to the same root cause; `ImagePullBackOff` just means the error has been happening for a while.

---

## Common Causes

1. **Wrong image name or tag** — typo in the image reference (e.g., `myapp:latst` instead of `myapp:latest`), or a tag that doesn't exist in the registry.
2. **Image deleted from registry** — the tag was overwritten or the image was removed after the Deployment was created.
3. **Private registry without imagePullSecret** — Kubernetes has no credentials to authenticate to the registry.
4. **Docker Hub rate limit** — anonymous pulls from Docker Hub are rate-limited (100 pulls/6h per IP).
5. **Network issue** — the node cannot reach the registry (DNS failure, firewall, proxy misconfiguration).
6. **Registry certificate error** — self-signed or expired TLS certificate on a private registry.

---

## Diagnosis Steps

```bash
# Step 1 — See the exact pull error
oc describe pod <pod-name> -n <namespace>
# Look for events like:
#   Failed to pull image "registry/image:tag": rpc error: ... not found
#   Failed to pull image "registry/image:tag": unauthorized: authentication required
#   Back-off pulling image "registry/image:tag"

# Step 2 — Confirm the image reference in the pod spec
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].image}'

# Step 3 — Check if an imagePullSecret is configured
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.imagePullSecrets}'

# Step 4 — Test pull manually from the node (if you have node access)
# SSH into the node, then:
docker pull <image:tag>
# or: crictl pull <image:tag>
```

---

## Remediation

### Cause: Wrong tag — correct the image reference
```bash
oc set image deployment/<deployment-name> \
  <container-name>=<registry>/<image>:<correct-tag> \
  -n <namespace>
```

### Cause: Docker Hub rate limit — use IfNotPresent pull policy
```bash
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"IfNotPresent"}]'
```
> This avoids re-pulling if the image is already cached on the node.

### Cause: Private registry — create and attach an imagePullSecret
```bash
# Create the secret with registry credentials
oc create secret docker-registry <secret-name> \
  --docker-server=<registry-url> \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> \
  -n <namespace>

# Attach it to the Deployment
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/imagePullSecrets","value":[{"name":"<secret-name>"}]}]'
```

### Cause: Docker Hub rate limit — authenticate to Docker Hub
```bash
oc create secret docker-registry dockerhub-creds \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=<dockerhub-username> \
  --docker-password=<dockerhub-token> \
  -n <namespace>
```

---

## Risk Level
- Setting a corrected image tag: **low**
- Changing imagePullPolicy to IfNotPresent: **low** (may serve stale cached image)
- Creating imagePullSecret: **low**

---

## Follow-up Actions
1. After fix: `oc get pod <pod-name> -n <namespace> -w` — confirm pod transitions to `Running`.
2. Verify the correct image version is running: `oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].image}'`
3. For production: enforce image tag pinning (never use `:latest`) and use a private registry mirror to avoid rate limits.
