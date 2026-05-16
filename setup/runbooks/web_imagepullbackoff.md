---
type: web
agent: Platform
---

Source: https://containersolutions.github.io/runbooks/posts/kubernetes/imagepullbackoff/
Title: Pod In ImagePullBackOff State – Runbooks

## Overview

An ImagePullBackOff error occurs when a Pod startup fails due to an inability to pull the image.

```
ImagePullBackOff
```

## Check RunBook Match

When running a kubectl get pods command, you will see a line like this in the output for your pod:

```
kubectl get pods
```

```
NAME                     READY     STATUS             RESTARTS   AGE
nginx-7ef9efa7cd-qasd2   0/1       ImagePullBackOff   0          1m
```

```
NAME                     READY     STATUS             RESTARTS   AGE
nginx-7ef9efa7cd-qasd2   0/1       ImagePullBackOff   0          1m
```

## Initial Steps Overview

* Gather information
Gather information

* Examine Events section in describe output
Examine Events section in describe output

```
Events
```

* Check the error message
Check the error message

## Detailed Steps

## 1) Gather information

Run this commands to gather relevant information in one step:

```
kubectl describe -n [NAMESPACE_NAME] pod [POD_NAME]` > /tmp/runbooks_describe_pod.txt
```

```
kubectl describe -n [NAMESPACE_NAME] pod [POD_NAME]` > /tmp/runbooks_describe_pod.txt
```

## 2) Examine Events section in describe output

```
Events
```

If you see lines that look like:

```
Warning  Failed     27s (x4 over 62s)   kubelet, gke-cs-79ec0e47-kfkc  Error: ImagePullBackOff
Warning  Failed     12s (x4 over 92s)  kubelet, gke-cs-79ec0e47-kfkc  Failed to pull image "nginx": rpc error: code = Unknown desc = Error response from daemon: repository nginx not found: does not exist or no pull access
Warning  Failed     12s (x4 over 93s)  kubelet, gke-cs-79ec0e47-kfkc  Error: ErrImagePull
```

```
Warning  Failed     27s (x4 over 62s)   kubelet, gke-cs-79ec0e47-kfkc  Error: ImagePullBackOff
Warning  Failed     12s (x4 over 92s)  kubelet, gke-cs-79ec0e47-kfkc  Failed to pull image "nginx": rpc error: code = Unknown desc = Error response from daemon: repository nginx not found: does not exist or no pull access
Warning  Failed     12s (x4 over 93s)  kubelet, gke-cs-79ec0e47-kfkc  Error: ErrImagePull
```

Then this indicates that the image repository you have specified does not exist on the Docker registry that your cluster is pointed at.

A common list of errors that can cause this are:

* Not specifying the repository (eg myprivaterepository/
Not specifying the repository (eg myprivaterepository/

* Not specifying the image in full (eg myimage instead of myusername/myimage)
Not specifying the image in full (eg myimage instead of myusername/myimage)

```
myimage
```

```
myusername/myimage
```

* Not specifying the tag (eg myimage instead of myimage:1.1), if the image doesn’t have a default latest tag
Not specifying the tag (eg myimage instead of myimage:1.1), if the image doesn’t have a default latest tag

```
myimage
```

```
myimage:1.1
```

```
latest
```

Generally, images will be pulled from the Docker Hub registry by default. However, it’s also possible that your cluster is pointed at another, private registry (or registries)

If the error specifies that the manifest is unavailable:

```
Warning  Failed     10m (x4 over 6m)    kubelet, gke-cs-79ec0e47-kfkc  Failed to pull image "nginx:latestt": rpc error: code = Unknown desc = Error response from daemon: manifest for nginx:latestt not found
```

```
Warning  Failed     10m (x4 over 6m)    kubelet, gke-cs-79ec0e47-kfkc  Failed to pull image "nginx:latestt": rpc error: code = Unknown desc = Error response from daemon: manifest for nginx:latestt not found
```

then this indicates that the specific version of the Docker repository is not available. Confirm that the image is available, and update accordingly if this is the case.

If the error specifies that authorization failed:

```
Warning  Failed     100s (x4 over 3m6s)  kubelet, dali      Failed to pull image "imiell/bad-dockerfile-private": rpc error: code = Unknown desc = failed to resolve image "docker.io/imiell/bad-dockerfile-private:latest": no available registry endpoint: pull access denied, repository does not exist or may require authorization: server message: insufficient_scope: authorization failed
```

```
Warning  Failed     100s (x4 over 3m6s)  kubelet, dali      Failed to pull image "imiell/bad-dockerfile-private": rpc error: code = Unknown desc = failed to resolve image "docker.io/imiell/bad-dockerfile-private:latest": no available registry endpoint: pull access denied, repository does not exist or may require authorization: server message: insufficient_scope: authorization failed
```

then the container image you have requested may be inaccessible without credentials being supplied; see Solution A)

## 3) Check registry is accessible

It may be that there is a network issue between your Kubernetes node and the registry.

To debug this (and if you have admin access), you may need to log into the kubernetes node the container was assigned to (the /tmp/runbooks_describe_pod.txt file will have the host name in it) and run the container runtime command to download and run by hand.

```
/tmp/runbooks_describe_pod.txt
```

## Solutions List

A) Add credentials

## Solutions Detail

## A) Add credentials

To access a private repository, you will need to:

* add credentials in a secret
add credentials in a secret

* reference the secret in your pod specification
reference the secret in your pod specification

See here for more information.

## Check Resolution

If the pod starts up with status RUNNING according to the output of kubectl get pods, then the issue has been resolved.

```
RUNNING
```

```
kubectl get pods
```

If there is a different status, then it may be that this issue is resolved, but a new issue has been revealed.

## Further Steps

None

## Further Information

Kubelet logs

Images documentation

## Owner

Ian Miell