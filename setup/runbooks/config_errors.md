---
type: kubernetes
agent: Platform
---

﻿# Runbook — CreateContainerConfigError / Missing Secret or ConfigMap

**Symptom**: The pod is stuck in `Waiting` state and never starts. No logs are available because the container never launches.
**Indicators**: `CreateContainerConfigError` in `oc describe pod` events, or `oc get pod` showing `STATUS: Init:Error` / `ContainerCreating` indefinitely.

---

## Common Causes

1. A `Secret` referenced by the pod spec (via `envFrom`, `env.valueFrom.secretKeyRef`, or `volumeMount`) does not exist in the namespace.
2. A `ConfigMap` referenced by the pod spec does not exist in the namespace.
3. The resource exists but in a different namespace than the pod.
4. A key referenced inside an existing Secret or ConfigMap does not exist (`secretKeyRef.key` mismatch).
5. The Secret or ConfigMap was deleted after the Deployment was created.

---

## Diagnosis Steps

```bash
# Identify the exact missing resource from events
oc describe pod <pod-name> -n <namespace>
# Look for lines like:
#   Error: secret "my-secret" not found
#   Error: configmap "my-config" not found

# Confirm the resource is absent
oc get secret -n <namespace>
oc get configmap -n <namespace>

# Check what keys are referenced in the deployment spec
oc get deployment <deployment-name> -n <namespace> -o yaml | grep -A5 'secretKeyRef\|configMapKeyRef\|envFrom'
```

---

## Remediation

### Case 1 — Missing Secret
```bash
oc create secret generic <secret-name> \
  --from-literal=<KEY_NAME>=<placeholder-value> \
  -n <namespace>
```
> Replace `<secret-name>` and `<KEY_NAME>` with the exact names found in the describe output.
> Use a real value or a safe placeholder — the pod will restart automatically once the secret exists.

### Case 2 — Missing ConfigMap
```bash
oc create configmap <configmap-name> \
  --from-literal=<KEY_NAME>=<default-value> \
  -n <namespace>
```

### Case 3 — Wrong key inside an existing Secret
```bash
# List current keys in the secret
oc get secret <secret-name> -n <namespace> -o jsonpath='{.data}' | python3 -m json.tool

# Patch the secret to add the missing key
oc patch secret <secret-name> -n <namespace> \
  --type='json' \
  -p='[{"op":"add","path":"/data/<KEY_NAME>","value":"'$(echo -n "value" | base64)'"}]'
```

---

## Important Notes

- **Never delete and recreate the pod** to fix this — the pod will still crash because the root cause is the missing resource, not the pod itself.
- After creating the missing Secret or ConfigMap, Kubernetes will automatically retry starting the container. No manual pod restart is needed.
- If the pod was created by a Deployment, the new pod will be scheduled within seconds.

---

## Risk Level
- Creating a missing Secret or ConfigMap with a placeholder: **low**
- Using incorrect secret values in production: **high** (application may fail at runtime)

---

## Follow-up Actions
1. Confirm the pod transitions to `Running` after creating the resource: `oc get pod <pod-name> -n <namespace> -w`
2. Update the placeholder secret value with the real credentials via your secrets manager (Vault, AWS Secrets Manager, etc.).
3. Add the Secret/ConfigMap creation to your deployment pipeline to prevent recurrence.
