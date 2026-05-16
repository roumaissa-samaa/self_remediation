---
type: kubernetes
agent: Platform
---

﻿# Runbook — Init Container Failure

**Symptom**: The pod is stuck in `Init:Error` or `Init:CrashLoopBackOff` state. The main application container never starts.
**Indicators**: `oc get pod` shows `Init:0/1`, `Init:Error`, or `Init:CrashLoopBackOff`. Events reference an init container by name.

---

## How Init Containers Work

Init containers run to completion **before** any main container starts. They run sequentially. If any init container fails (exits with non-zero code), Kubernetes restarts it (subject to `restartPolicy`) and the main container never starts. This makes them a common source of "pod stuck at startup" incidents.

---

## Common Causes

1. **Dependency not ready** — init container waits for a service (database, API, message broker) that is not yet available.
2. **Missing secret or configmap** — init container references an env var from a secret that doesn't exist.
3. **Wrong image** — init container uses a non-existent image tag.
4. **Script logic error** — custom shell script in the init container exits with code 1.
5. **Permission issue** — init container cannot write to a shared volume due to `securityContext` mismatch.
6. **Network policy blocking** — init container cannot reach the dependency it's checking.

---

## Diagnosis Steps

```bash
# Step 1 — Identify which init container is failing and its exit code
oc describe pod <pod-name> -n <namespace>
# Look for the "Init Containers" section:
#   State: Terminated, Exit Code: 1, Reason: Error

# Step 2 — Read logs from the failing init container
oc logs <pod-name> -n <namespace> -c <init-container-name>
# For previous attempt (if restarting):
oc logs <pod-name> -n <namespace> -c <init-container-name> --previous

# Step 3 — List all init containers and their status
oc get pod <pod-name> -n <namespace> -o json | \
  python3 -c "import sys,json; [print(c['name'], c.get('state')) for c in json.load(sys.stdin)['status'].get('initContainerStatuses', [])]"

# Step 4 — Check if the dependency service exists
oc get service -n <namespace>
oc get endpoints -n <namespace>
```

---

## Remediation

### Cause: Dependency service not ready (most common)
The init container is typically a wait loop like:
```sh
until nc -z <service-name> <port>; do sleep 2; done
```
Fix: ensure the dependency is deployed and its pod is running.
```bash
# Check the dependency pod
oc get pod -n <namespace> -l app=<dependency-name>

# Check the dependency service
oc get service <service-name> -n <namespace>
oc get endpoints <service-name> -n <namespace>
```

### Cause: Missing secret referenced by init container
```bash
# Identify the missing secret from describe output
oc describe pod <pod-name> -n <namespace> | grep "secret"

# Create the missing secret
oc create secret generic <secret-name> \
  --from-literal=<KEY>=<value> \
  -n <namespace>
```

### Cause: Script error in init container — debug interactively
```bash
# Run the init container image interactively to debug the script
oc run debug-init --image=<init-container-image> \
  -n <namespace> \
  --restart=Never \
  --rm -it \
  -- /bin/sh
```

### Force restart the pod after fixing the root cause
Init containers do not restart automatically if the pod is in a failed state. Delete the pod to trigger a new attempt (the Deployment will recreate it):
```bash
oc delete pod <pod-name> -n <namespace>
```

---

## Risk Level
- Reading logs and events: **low**
- Deleting the failed pod (when controlled by a Deployment): **low**
- Manually creating missing secrets: **low** (use placeholder values, update later)

---

## Follow-up Actions
1. After fixing the root cause: `oc get pod -n <namespace> -w` — confirm init containers complete and main container starts.
2. Check init container logs again to confirm they exit with code 0.
3. If init containers implement readiness waiting, consider replacing them with `startupProbe` or proper service dependencies in your orchestration layer.
