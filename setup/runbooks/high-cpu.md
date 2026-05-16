---
type: kubernetes
agent: Platform
---

# Runbook — High CPU / CPU Throttling

**Symptom**: The application is slow or unresponsive despite being in `Running` state. No crashes, but latency spikes.
**Indicators**: `oc adm top pod` shows CPU near or at the limit, Prometheus shows `container_cpu_cfs_throttled_seconds_total` increasing, P99 latency elevated.

---

## CPU Requests vs Limits — Key Difference

| Setting | Effect |
|---------|--------|
| `requests.cpu` | Used for **scheduling** — guarantees this CPU on the node |
| `limits.cpu` | Used for **throttling** — the kernel never allows more than this |

When a container hits its CPU **limit**, the Linux CFS (Completely Fair Scheduler) throttles it — the process is paused for the rest of the scheduling period. This causes latency spikes without any crash or restart.

---

## Common Causes

1. **CPU limit too low** — the application needs more CPU than configured (e.g., during startup, GC, or load spikes).
2. **Noisy neighbor** — another pod on the same node is consuming CPU, reducing available shares for your pod.
3. **Infinite loop or CPU leak** — application bug consuming 100% of one core continuously.
4. **Synchronous blocking calls** — app blocked on I/O while holding a thread, exhausting the thread pool under CPU limit.
5. **JVM / GC pressure** — frequent garbage collection consuming all available CPU.

---

## Diagnosis Steps

```bash
# Step 1 — Check current CPU usage vs limit
oc adm top pod <pod-name> -n <namespace> --containers
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[0].resources}'

# Step 2 — Check node-level CPU pressure
oc adm top nodes
oc describe node <node-name>   # check Allocatable vs Requests

# Step 3 — Check CPU throttling metric (requires Prometheus access)
# Query: rate(container_cpu_cfs_throttled_seconds_total{pod="<pod>",namespace="<ns>"}[5m])
# > 0.25 (25% throttled) is significant

# Step 4 — Get a thread/CPU profile from inside the pod (Java example)
oc exec <pod-name> -n <namespace> -- kill -3 1   # triggers thread dump to stdout
oc logs <pod-name> -n <namespace> | tail -200

# Step 5 — Check for CPU-heavy processes inside the pod
oc exec <pod-name> -n <namespace> -- top -b -n 1 | head -20
```

---

## Remediation

### Increase CPU limit
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[
    {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/cpu","value":"2000m"},
    {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/cpu","value":"500m"}
  ]'
```

### Remove CPU limit (recommended on OpenShift for latency-sensitive apps)
```bash
oc patch deployment/<deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"remove","path":"/spec/template/spec/containers/0/resources/limits/cpu"}]'
```
> On OpenShift, it is a best practice to set CPU **requests** but NOT CPU **limits** for application workloads. CPU limits cause throttling; requests are sufficient for fair scheduling.

### Scale horizontally to distribute load
```bash
oc scale deployment/<deployment-name> --replicas=3 -n <namespace>

# Or use HPA for automatic scaling
oc autoscale deployment/<deployment-name> -n <namespace> \
  --min=2 --max=10 --cpu-percent=70
```

### Tune JVM for containerized environments
```bash
oc set env deployment/<deployment-name> -n <namespace> \
  JAVA_OPTS="-XX:+UseContainerSupport -XX:ActiveProcessorCount=2 -XX:MaxRAMPercentage=75.0"
```

---

## Risk Level
- Increasing CPU limit: **low**
- Removing CPU limit: **low** (but monitor node saturation afterwards)
- Adding HPA: **low**

---

## Follow-up Actions
1. After patching: monitor `oc adm top pod <pod-name> -n <namespace>` every 30s for 5 minutes.
2. Check `container_cpu_cfs_throttled_seconds_total` drops to near zero.
3. If CPU is still high after removing the limit, the issue is a code-level bug — profile the application.
4. Review node `Allocatable` CPU vs total `Requests` to detect node-level overcommit.
