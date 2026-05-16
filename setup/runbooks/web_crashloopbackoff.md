---
type: web
agent: Platform
---

Source: https://containersolutions.github.io/runbooks/posts/kubernetes/crashloopbackoff/
Title: Pod In CrashLoopBackOff State – Runbooks

## Overview

A CrashLoopBackOff error occurs when a pod startup fails repeatedly in Kubernetes.

```
CrashLoopBackOff
```

## Check RunBook Match

When running a kubectl get pods command, you will see a line like this in the output for your pod:

```
kubectl get pods
```

```
NAME                     READY     STATUS             RESTARTS   AGE
nginx-7ef9efa7cd-qasd2   0/1       CrashLoopBackOff   2          1m
```

```
NAME                     READY     STATUS             RESTARTS   AGE
nginx-7ef9efa7cd-qasd2   0/1       CrashLoopBackOff   2          1m
```

If you see something like:

```
NAME                     READY     STATUS                  RESTARTS   AGE
pod1-7ef9efa7cd-qasd2    0/2       Init:CrashLoopBackOff   2          1m
```

```
NAME                     READY     STATUS                  RESTARTS   AGE
pod1-7ef9efa7cd-qasd2    0/2       Init:CrashLoopBackOff   2          1m
```

then continue with this runbook, bearing in mind that the problem is likely specific to the init container.

## Initial Steps Overview

* Gather information
Gather information

* Examine Events section in describe output
Examine Events section in describe output

```
Events
```

* Check the exit code
Check the exit code

* Check readiness/liveness probes
Check readiness/liveness probes

* Check common application issues
Check common application issues

## Detailed Steps

## 1) Gather information

Run these commands to gather relevant information in one step:

```
kubectl describe -n [NAMESPACE_NAME] pod [POD_NAME] > /tmp/runbooks_describe_pod.txt
kubectl logs --all-containers -n [NAMESPACE_NAME] > /tmp/runbooks_pod_logs.txt
kubectl logs --all-containers --previous -n [NAMESPACE_NAME] > /tmp/runbooks_previous_pod_logs.txt
```

```
kubectl describe -n [NAMESPACE_NAME] pod [POD_NAME] > /tmp/runbooks_describe_pod.txt
kubectl logs --all-containers -n [NAMESPACE_NAME] > /tmp/runbooks_pod_logs.txt
kubectl logs --all-containers --previous -n [NAMESPACE_NAME] > /tmp/runbooks_previous_pod_logs.txt
```

## 2) Examine Events section in output

```
Events
```

Look at the Events section of your /tmp/runbooks_describe_pod.txt file.

```
Events
```

```
/tmp/runbooks_describe_pod.txt
```

```
Back-off restarting failed container
```

If you see a warning like the following in your /tmp/runbooks_describe_pod.txt output:

```
/tmp/runbooks_describe_pod.txt
```

```
Warning  BackOff    8s (x2 over 9s)    kubelet, dali      Back-off restarting failed container
```

```
Warning  BackOff    8s (x2 over 9s)    kubelet, dali      Back-off restarting failed container
```

then the pod has repeatedly failed to start up successfully.

Make a note of any containers that have a State of Waiting in the description and a description of CrashLoopBackOff. These are the containers you will need to fix.

```
State
```

```
Waiting
```

```
CrashLoopBackOff
```

## 3) Check the exit code

Examine the describe output, and look for the Exit Code.

This exit code implies that the specified container command completed ‘sucessfully’, but too often for Kubernetes to accept as working.

Did you fail to specify a command the pod spec, and the container ran (for example) a default shell command that failed? If so, you will need to add the right command. See solution c.

Examine the logs in /tmp/runbooks_describe_pod.txt to see whether there are any clues there as to why the application terminated.

```
/tmp/runbooks_describe_pod.txt
```

The container failed to run its command successfully, and returned an exit code of 1. This is an application failure within the process that was started, but return with a failing exit code some time after.

If this is happening only with all pods running on your cluster, then there may be a problem with your notes. Check nodes are OK on your cluster with: kubectl get nodes -o wide.

```
kubectl get nodes -o wide
```

Examine the logs in /tmp/runbooks_describe_pod.txt and determine resolution in the context of the command that ran as specified in the image, or debug the application directly.

```
/tmp/runbooks_describe_pod.txt
```

An exit code of 2 indicates either that the application chose to return that error code, or (by convention) there was a misuse of a shell builtin. Check your pod’s command specification to ensure that the command is correct. If you think it is correct, try running the image locally with a shell and run the command directly.

```
2
```

```
misuse of a shell builtin
```

An exit code of 128 indicates that the container could not run. Check this by examining the /tmp/runbooks_describe_pod.txt output to see whether the LastState Reason is: ContainerCannotRun.

```
128
```

```
/tmp/runbooks_describe_pod.txt
```

```
LastState
```

```
Reason
```

```
ContainerCannotRun
```

This indicates that the container was killed with signal 9

This can be due to one of the following reasons:

This may be because your application needs more resources than it’s allowed to use, or your application is using more than it should. Which of these is the case is context-specific, so you will need to use your judgement.

If you want to increase your pod’s resource request, see solution E.

You will also likely see Reason: OOM in the container in the /tmp/runbooks_describe_pod.txt output.

```
Reason: OOM
```

```
/tmp/runbooks_describe_pod.txt
```

If you see a warning like this in the Events output of /tmp/runbooks_describe_pod.txt:

```
/tmp/runbooks_describe_pod.txt
```

```
Warning  Unhealthy  13s (x3 over 23s)  kubelet, dali      Liveness probe failed: cat: can't open '/tmp/healthy': No such file or directory
```

```
Warning  Unhealthy  13s (x3 over 23s)  kubelet, dali      Liveness probe failed: cat: can't open '/tmp/healthy': No such file or directory
```

Then you will need to check your liveness probes. Skip to step 4.

## 4) Check liveness/readiness probes

If these are too short for the application initialization time, then Kubernetes may be killing the application too early.

Whether the time taken to start is longer because there is a problem, or whether the time take to start is genuinely longer than the probe times is a judgement for the reader/application owner.

If the probe times are too short, see Solution D) below.

See here for more background information.

## 5) Check common application issues

Some common application problems to consider that may not be specific to your context:

* If your application requires privileged access to function, then you may need to set allowPrivilegeEscalation (some core components rely on this, eg coreDNS)
If your application requires privileged access to function, then you may need to set allowPrivilegeEscalation (some core components rely on this, eg coreDNS)

```
allowPrivilegeEscalation
```

* SELinux or AppArmor controls may be preventing your application from running
SELinux or AppArmor controls may be preventing your application from running

Note that by allowing privilege escalation, you may be undermining necessary controls, or allowing your application to do something that is not allowed in your context.

## Solutions List

A) Fix the application

B) Add a startup command

C) Correct the container or spec to run a command that exists in the container, and is executable

D) Adjust the time for the liveness/readiness probes

E) Increase resource request

## Solutions Detail

## A) Fix the application

This is outside the scope of this runbook.

## B) Add a startup command

In order for a pod to start, it needs a startup command. Consider adding one to the container image, or adding a command to the container specification(s) within the pod.

## C) Correct the container or spec to run a command that exists in the container

If the command was not specified (both in the image and the pod specification), then add a command in either place.

If the command was not executable, make it executable. This may require a change to the container build, or specifying a correct executable.

## D) Adjust the time for the liveness/readiness probes

See here for information on how and what to change in your pod specification.

## E) Increase resource request

If you want to increase the resources allocated to your pod, see here.

## Check Resolution

If the pod starts up with status RUNNING according to the output of kubectl get pods, then the issue has been resolved.

```
RUNNING
```

```
kubectl get pods
```

If there is a different status, then it may be that this particular issue is resolved, but a new issue has been revealed, and the runbook needs to be re-followed.

If it has not been resolved by this runbook, then please comment below.

## Further Steps

None

## Further Information

Init containers

Probes

Kubelet logs

## Owner

Ian Miell