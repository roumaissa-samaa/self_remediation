---
type: kubernetes
agent: Platform
---

﻿# Runbook — OOMKilled (Out of Memory Killed)

**Symptom**: The container process is killed by the Linux kernel OOM killer because it exceeded its memory limit.
**Indicators**: `Reason: OOMKilled`, exit code `137`, `Last State: Terminated` in `oc describe pod`.

---

## How OOMKilled Works in Kubernetes

Kubernetes enforces `resources.limits.memory` using Linux cgroups. When a container exceeds this limit, the kernel's Out-Of-Memory (OOM) killer sends `SIGKILL` (signal 9) to the process, resulting in exit code 137 (128 + 9). This is different from a graceful shutdown.

---

## Common Causes

1. **Limits too low** — the application legitimately needs more memory than configured.
2. **Memory leak** — unbounded growth over time; application allocates memory it never frees.
3. **JVM heap not container-aware** — Java pre-JDK 10 ignores cgroup limits and allocates based on host RAM.
4. **Large dataset in memory** — batch jobs or analytics workloads loading entire files into RAM.
5. **Missing memory request** — scheduler places the pod on a node that's already memory-pressured.
6. **Sidecar contention** — a sidecar container (e.g., log forwarder) consuming memory alongside the main container.

---

## Diagnosis Steps

```bash
# Step 1 — Confirm OOMKilled and see last exit code
oc describe pod <pod-name> -n <namespace>
# Look for:
#   Last State:     Terminated
#     Reason:       OOMKilled
#     Exit Code:    137

# Step 2 — Check current memory usage
oc top pod <pod-name> -n <namespace>
oc top pod <pod-name> -n <namespace> --containers

# Step 3 — Check configured limits and requests
oc get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources}'

# Step 4 — Read previous logs to identify memory-intensive operation at crash time
oc logs <pod-name> -n <namespace> --previous --tail=150

# Step 5 — Check if the Deployment has a memory limit defined
oc get deployment <deployment-name> -n <namespace> -o yaml | grep -A10 resources
```

---

## Remediation

### Immediate — increase memory limit on the Deployment
Use action **patch_deployment** on the Deployment (never delete_pod — the pod is recreated with the same limit and OOMKills again).

Strategic merge patch to increase memory limit to 512Mi:
```json
{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","resources":{"limits":{"memory":"512Mi"}}}]}}}}
```

Set both request and limit together (512Mi limit, 256Mi request):
```json
{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","resources":{"requests":{"memory":"256Mi"},"limits":{"memory":"512Mi"}}}]}}}}
```

> Always patch the Deployment, not the Pod. Pod patches are ephemeral — lost on the next restart.

### Java applications — enable container-aware JVM
Add to container `args` or `JAVA_OPTS` environment variable:
```
-XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0
```
This prevents the JVM from allocating heap based on total host RAM.

### Auto-scaling to handle load spikes
```bash
oc autoscale deployment <deployment-name> -n <namespace> \
  --min=2 --max=10 --cpu-percent=70
```

---

## Memory Sizing Guidelines

| Application Type | Recommended Limit Strategy |
|-----------------|---------------------------|
| Node.js / Python | Set limit to 2x observed peak usage |
| Java (Spring Boot) | Set limit to heap size + 256Mi overhead |
| Go | Set limit to 1.5x observed peak usage |
| Batch jobs | Set limit to max dataset size + 20% headroom |

---

## Risk Level
- Increasing memory limit: **low**
- Patching deployment (triggers rolling restart): **medium**
- Ignoring recurring OOMKilled without fixing leak: **high**

---

## Follow-up Actions
1. After patching: `oc top pod <pod-name> -n <namespace>` — confirm memory stabilizes below the new limit.
2. Set up a Prometheus alert: `container_memory_usage_bytes > 0.9 * container_spec_memory_limit_bytes`.
3. If the container keeps growing without bound → memory leak in application code.
4. Consider installing VPA (VerticalPodAutoscaler) for automatic memory right-sizing.
