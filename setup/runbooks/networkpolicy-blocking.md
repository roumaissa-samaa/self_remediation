---
type: kubernetes
agent: Platform
---

# Runbook — NetworkPolicy Blocking Traffic

**Symptom**: Two pods cannot communicate even though DNS resolves correctly and the Service exists.
**Indicators**: `Connection refused` or `Connection timed out` between specific namespaces or pods, but the same request works from other pods.

---

## How NetworkPolicies Work

A `NetworkPolicy` is a namespace-scoped firewall rule. By default (no policy), all pod-to-pod traffic is allowed. Once **any** NetworkPolicy selects a pod, all traffic not explicitly allowed is denied. This is the "deny-by-default" model.

---

## Common Causes

1. **Missing ingress allow rule** — a NetworkPolicy exists in the target namespace but has no rule permitting traffic from the source.
2. **Namespace isolation enabled** — the namespace has a default-deny policy (common in enterprise clusters).
3. **Wrong pod selector labels** — the `podSelector` in the policy doesn't match the actual pod labels.
4. **Missing egress rule** — the source pod's namespace has an egress NetworkPolicy that blocks outbound traffic.
5. **Cross-namespace traffic not allowed** — the policy uses `podSelector` but no `namespaceSelector`.

---

## Diagnosis Steps

```bash
# Step 1 — List all NetworkPolicies in the target namespace
oc get networkpolicy -n <target-namespace>
oc describe networkpolicy <policy-name> -n <target-namespace>

# Step 2 — Test connectivity from source pod
oc exec -it <source-pod> -n <source-namespace> -- \
  curl -v http://<service-name>.<target-namespace>.svc.cluster.local:<port>

# Step 3 — Test raw TCP connectivity
oc run nettest --image=busybox --restart=Never --rm -it -n <source-namespace> \
  -- nc -zv <target-pod-ip> <port>

# Step 4 — Check pod labels (must match policy podSelector)
oc get pods -n <target-namespace> --show-labels

# Step 5 — Check namespace labels (needed for namespaceSelector)
oc get namespace <source-namespace> --show-labels
```

---

## Remediation

### Allow traffic from a specific namespace
```bash
oc apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-<source-namespace>
  namespace: <target-namespace>
spec:
  podSelector: {}
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: <source-namespace>
EOF
```

### Allow traffic from specific pods in another namespace
```bash
oc apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-app
  namespace: <target-namespace>
spec:
  podSelector:
    matchLabels:
      app: <target-app>
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: <source-namespace>
      podSelector:
        matchLabels:
          app: <source-app>
    ports:
    - protocol: TCP
      port: 8080
EOF
```

### Temporary — allow all ingress (debug only, revert after)
```bash
oc apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-all-debug
  namespace: <target-namespace>
spec:
  podSelector: {}
  ingress:
  - {}
EOF
# After debugging, delete this policy:
oc delete networkpolicy allow-all-debug -n <target-namespace>
```

---

## Risk Level
- Adding a specific allow rule: **low**
- Adding allow-all rule: **high** — removes namespace isolation, delete immediately after debugging

---

## Follow-up Actions
1. After fix: re-run the `curl` test to confirm connectivity.
2. Document all intentional NetworkPolicies — accidental policies are a common incident cause.
3. On OpenShift, ensure the `kubernetes.io/metadata.name` label is present on namespaces (auto-set since OCP 4.9).
