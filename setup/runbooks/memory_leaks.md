---
type: kubernetes
agent: Platform
---

﻿# Runbook — OOMKilled / Memory Leak

**Symptom**: Container is terminated due to exceeding memory limits.

**Indicators**:
- `Reason: OOMKilled`
- Exit code `137`
- High restart count
- Pod repeatedly restarting (`CrashLoopBackOff` possible)

---

## Diagnosis

# Check termination reason
oc describe pod <pod-name> -n <namespace>

# Check memory usage
oc top pod <pod-name> -n <namespace>

# Check memory limits & requests
oc get deployment <deployment-name> -n <namespace> \
  -o jsonpath='{.spec.template.spec.containers[*].resources}'

# Check logs before crash
oc logs <pod-name> -n <namespace> --previous --tail=100

---

## Root Cause

- Memory limit too low for workload
- Memory leak in application
- High load or large in-memory processing
- Missing or incorrect memory requests
- JVM not respecting container limits (Java apps)

---

## Remediation

### Increase memory limits
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"256Mi"}]'

### Add or adjust memory requests
oc patch deployment <deployment-name> -n <namespace> \
  --type=json \
  -p '[
    {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"256Mi"},
    {"op":"replace","path":"/spec/template/spec/containers/0/resources/requests/memory","value":"128Mi"}
  ]'

### Restart pod (if needed)
oc delete pod <pod-name> -n <namespace>

### Enable autoscaling (recommended)
oc autoscale deployment <deployment-name> -n <namespace> \
  --min=2 --max=5 --cpu-percent=70

### Java fix (if applicable)
-XX:+UseContainerSupport -XX:MaxRAMPercentage=75.0

---

## Risk Level

- Restart pod: low  
- Increase memory limits: low  
- Patch deployment: medium  
- Ignoring memory leak: high  

---

## Follow-up Actions

- Monitor memory usage (`oc top pod`)
- Add Prometheus alerts for memory
- Analyze application for memory leaks
- Use VerticalPodAutoscaler (VPA) for tuning