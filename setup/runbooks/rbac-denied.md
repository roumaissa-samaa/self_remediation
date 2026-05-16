---
type: kubernetes
agent: Platform
---

# Runbook — RBAC Permission Denied

**Symptom**: An application or user cannot perform a Kubernetes API action and receives an authorization error.
**Indicators**: `Error from server (Forbidden)`, `User "system:serviceaccount:..." cannot get resource "pods"`, `403 Forbidden` in application logs.

---

## How RBAC Works in Kubernetes / OpenShift

Every request to the API server is checked against:
1. **Who** is making the request (ServiceAccount, User, Group)
2. **What** they want to do (verb: get, list, create, patch, delete...)
3. **On what** resource (pods, deployments, secrets...)
4. **In which scope** (namespace via Role/RoleBinding, or cluster-wide via ClusterRole/ClusterRoleBinding)

---

## Common Causes

1. **ServiceAccount missing from pod spec** — pod uses the `default` ServiceAccount which has no permissions.
2. **RoleBinding missing** — a Role exists but is not bound to the ServiceAccount.
3. **Wrong namespace** — RoleBinding exists in namespace A but the pod runs in namespace B.
4. **Verb missing from Role** — the Role grants `get` but the app needs `list` or `watch`.
5. **Resource name typo** — `deployment` instead of `deployments` (plural is required in rules).

---

## Diagnosis Steps

```bash
# Step 1 — Check what the ServiceAccount can do
oc auth can-i --list \
  --as=system:serviceaccount:<namespace>:<serviceaccount-name> \
  -n <namespace>

# Step 2 — Test a specific permission
oc auth can-i get pods \
  --as=system:serviceaccount:<namespace>:<serviceaccount-name> \
  -n <namespace>
# Returns "yes" or "no"

# Step 3 — Find which ServiceAccount the pod uses
oc get pod <pod-name> -n <namespace> \
  -o jsonpath='{.spec.serviceAccountName}'

# Step 4 — List existing RoleBindings in namespace
oc get rolebindings,clusterrolebindings -n <namespace> -o wide | grep <serviceaccount-name>

# Step 5 — Describe the Role to see its rules
oc describe role <role-name> -n <namespace>
```

---

## Remediation

### Create a Role and bind it to the ServiceAccount
```bash
# Create the Role with necessary permissions
oc apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: <role-name>
  namespace: <namespace>
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log", "events"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets"]
  verbs: ["get", "list", "watch", "patch", "update"]
EOF

# Create the RoleBinding
oc apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: <role-name>-binding
  namespace: <namespace>
subjects:
- kind: ServiceAccount
  name: <serviceaccount-name>
  namespace: <namespace>
roleRef:
  kind: Role
  name: <role-name>
  apiGroup: rbac.authorization.k8s.io
EOF
```

### Add a specific verb to an existing Role
```bash
oc patch role <role-name> -n <namespace> --type=json \
  -p='[{"op":"add","path":"/rules/0/verbs/-","value":"watch"}]'
```

### Grant a pre-built ClusterRole (quick fix for read access)
```bash
# Read-only access to common resources in one namespace
oc adm policy add-role-to-user view \
  -z <serviceaccount-name> -n <namespace>
```

### Ensure the pod uses the correct ServiceAccount
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  -p '{"spec":{"template":{"spec":{"serviceAccountName":"<serviceaccount-name>"}}}}'
```

---

## Risk Level
- Granting `view` role: **low** — read-only
- Granting `edit` or `admin` role: **high** — broad write access
- Creating a scoped Role with specific verbs: **low** — principle of least privilege

---

## Follow-up Actions
1. After fix: re-run `oc auth can-i` to confirm the permission is now granted.
2. Audit all ServiceAccounts with overly broad permissions: `oc get clusterrolebindings -o wide | grep <namespace>`.
3. Follow least-privilege: grant only the specific verbs and resources the application needs.
4. On OpenShift, avoid binding `cluster-admin` to application ServiceAccounts.
