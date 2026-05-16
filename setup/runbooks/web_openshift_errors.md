---
type: web
agent: Platform
---

Source: https://medium.com/@morepravin1989/mastering-pod-error-troubleshooting-in-openshift-imagepullbackoff-crashloopbackoff-bac81832071a
Title: Mastering Pod Error Troubleshooting in OpenShift: ImagePullBackOff & CrashLoopBackOff

# Mastering Pod Error Troubleshooting in OpenShift: ImagePullBackOff & CrashLoopBackOff

When running workloads on Red Hat OpenShift, encountering pod errors like **ImagePullBackOff** or **CrashLoopBackOff** can disrupt deployments and delay delivery. This guide walks you through understanding, diagnosing, and resolving these errors step-by-step — along with additional common pod error states and their fixes.

## 1. Understanding ImagePullBackOff

**What it means:**
The cluster attempted to pull the container image for your pod, failed, and is now delaying retries (“backing off”) to avoid hammering the registry.

## Step-by-Step Resolution

### Step 1 — Identify the exact error

```bash
oc describe pod <pod-name> -n <namespace>
oc get events -n <namespace> --field-selector involvedObject.name=<pod-name> --sort-by=.lastTimestamp
```

Look for messages like `manifest unknown`, `authentication required`, or `x509: certificate signed by unknown authority`.

### Step 2 — Verify image reference

```bash
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].image}{"\n"}'
```

* Ensure registry, repository, and tag are correct.
* Check if the image actually exists in the registry.

### Step 3 — Fix authentication (private registries)

```bash
oc create secret docker-registry regcred \
  --docker-server=<registry> \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> -n <namespace>
```

```bash
oc secrets link default regcred --for=pull -n <namespace>
```

Verify the service account is linked:

```bash
oc describe sa default -n <namespace>
```

### Step 4 — Handle custom CAs or insecure registries

**Trusted CA:**

```bash
oc create configmap registry-ca -n openshift-config \
  --from-file=<registry-hostname>=ca.crt
```

```bash
oc patch image.config.openshift.io/cluster --type=merge \
  -p '{"spec":{"additionalTrustedCA":{"name":"registry-ca"}}}'
```

**Insecure registry (not recommended):**

```bash
oc patch image.config.openshift.io/cluster --type=merge \
  -p '{"spec":{"registrySources":{"insecureRegistries":["<registry>:<port>"]}}}'
```

### Step 5 — Verify network reachability

```bash
oc debug node/<node-name> -- chroot /host curl -v https://<registry>/v2/
```

* Check if firewalls, proxies, or OpenShift’s allowed registry policy are blocking access.

### Step 6 — Redeploy

Once the issue is fixed:

```bash
oc rollout restart deploy/<deployment-name> -n <namespace>
```

---

## 2. Understanding CrashLoopBackOff

**What it means:**
The container starts, fails, exits with a non-zero code, and Kubernetes delays the restart to avoid constant crashes.

## Step-by-Step Resolution

### Step 1 — Get logs

```bash
oc logs <pod-name> -c <container-name> -n <namespace> --previous
```

Look for application errors, missing environment variables, permission issues, or dependency failures.

### Step 2 — Check pod events

```bash
oc describe pod <pod-name> -n <namespace>
```

Events can reveal if liveness/readiness probes or OOM kills are triggering restarts.

### Step 3 — Address common causes

* **App configuration errors:** Missing secrets or wrong args.
* **Probe failures:** Relax thresholds or fix endpoint.
* **Permissions/SCC issues:** OpenShift runs containers as a random UID; adjust file permissions.
* **OOMKilled:** Increase memory requests/limits.
* **Dependency unavailability:** Ensure DB or API is reachable.
* **Port conflicts:** Match container’s listening port with Service/Probe configs.

### Example: Fixing SCC Permissions

```bash
RUN chgrp -R 0 /app && chmod -R g=u /app
USER 1001
```

---

## 3. Quick Reference: Other Common Pod States

| Status | Meaning & Cause | Fix |
|---|---|---|
| `ErrImagePull` | Bad image ref or auth error | Correct image, add pull secret |
| `CreateContainerConfigError` | Missing config/secret or bad volume mount | Create/mount correctly |
| `OOMKilled` | Container exceeded memory limit | Increase limits |
| `ContainerCreating` | Waiting for image pull or volume attach | Check registry/storage |
| `Pending` | No schedulable nodes or PVC unbound | Add capacity or fix PVC |

---

## 4. Proactive Prevention Tips

* Pin images by digest for immutability.
* Ship non-root images and make writable paths group-writable.
* Right-size resource requests/limits.
* Configure health probes with sensible delays.
* Centralize CA & registry settings in `image.config.openshift.io/cluster`.

**Conclusion:**
With a structured approach, most pod startup issues in OpenShift can be diagnosed and fixed within minutes. By combining logs, events, and container runtime insights, you can go from error state to healthy pod efficiently — and prevent future disruptions.
