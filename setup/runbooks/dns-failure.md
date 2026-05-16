---
type: kubernetes
agent: Platform
---

# Runbook — DNS Resolution Failure

**Symptom**: An application cannot reach other services by their hostname. Connections fail at the DNS lookup stage.
**Indicators**: `Temporary failure in name resolution`, `NXDOMAIN`, `dial tcp: lookup <service>: no such host` in application logs.

---

## Kubernetes DNS Architecture

In Kubernetes, CoreDNS (or OpenShift DNS Operator) provides in-cluster DNS. Each service gets a DNS name:
- Short form: `<service-name>` (works within same namespace)
- Full form: `<service-name>.<namespace>.svc.cluster.local`

Pod DNS is configured via `/etc/resolv.conf` injected by kubelet.

---

## Common Causes

1. **CoreDNS pods down or overloaded** — DNS queries time out for all pods in the cluster.
2. **Service does not exist** — the application references a service name that was deleted or misspelled.
3. **Wrong namespace** — the app calls `<service>` but the service is in a different namespace; need the FQDN.
4. **`ndots` misconfiguration** — high `ndots` causes many unnecessary DNS search path lookups, leading to timeouts.
5. **NetworkPolicy blocks CoreDNS** — a policy in the pod's namespace blocks UDP/TCP port 53 to the `kube-dns` service.
6. **Node DNS misconfigured** — node's `/etc/resolv.conf` is broken, affecting kubelet DNS injection.

---

## Diagnosis Steps

```bash
# Step 1 — Test DNS from inside the affected pod
oc exec -it <pod-name> -n <namespace> -- nslookup <service-name>
oc exec -it <pod-name> -n <namespace> -- nslookup <service-name>.<target-namespace>.svc.cluster.local

# Step 2 — Check /etc/resolv.conf inside the pod
oc exec -it <pod-name> -n <namespace> -- cat /etc/resolv.conf

# Step 3 — Run a dedicated DNS debug pod
oc run dns-debug --image=busybox --restart=Never --rm -it -n <namespace> \
  -- sh -c "nslookup kubernetes.default && nslookup <service-name>.<target-namespace>.svc.cluster.local"

# Step 4 — Check CoreDNS pods
oc get pods -n openshift-dns
oc logs -n openshift-dns -l dns.operator.openshift.io/daemonset-dns=default --tail=50

# Step 5 — Verify the Service exists and has endpoints
oc get service <service-name> -n <target-namespace>
oc get endpoints <service-name> -n <target-namespace>
```

---

## Remediation

### Fix — Service does not exist or wrong name
```bash
# List services in the target namespace
oc get services -n <target-namespace>

# Use the FQDN in the application config
# Format: <service-name>.<namespace>.svc.cluster.local
```

### Fix — CoreDNS pods overloaded or crashed
```bash
# Restart CoreDNS (OpenShift DNS DaemonSet)
oc rollout restart daemonset/dns-default -n openshift-dns

# Check if CoreDNS is throttled
oc adm top pods -n openshift-dns

# Scale up CoreDNS if needed (OpenShift uses DaemonSet — one per node by default)
oc describe daemonset dns-default -n openshift-dns
```

### Fix — NetworkPolicy blocking port 53
```bash
# Allow egress to kube-dns from the affected namespace
oc apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
EOF
```

### Fix — reduce ndots to improve DNS performance
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  -p '{"spec":{"template":{"spec":{"dnsConfig":{"options":[{"name":"ndots","value":"2"}]}}}}}'
```
> Default `ndots:5` causes 4 search-path attempts before trying the exact name. `ndots:2` is more efficient.

---

## Risk Level
- Restarting CoreDNS DaemonSet: **medium** — brief DNS interruption during pod restart on each node
- Adding DNS NetworkPolicy: **low**
- Changing `ndots`: **low**

---

## Follow-up Actions
1. After fix: re-run `oc exec ... -- nslookup <service-name>` to confirm resolution works.
2. Set up CoreDNS latency alert: `coredns_dns_request_duration_seconds_bucket` P99 > 100ms.
3. If CoreDNS is repeatedly overloaded, increase its memory/CPU limits in the DNS Operator config.
