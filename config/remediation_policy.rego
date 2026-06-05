package remediation

default allow = false
default deny_reason = "Command not authorized by remediation policy"

# ── Protected namespaces ──────────────────────────────────
protected_namespaces := {"kube-system", "cert-manager", "monitoring", "ingress-nginx"}

namespace_forbidden if {
    protected_namespaces[object.get(input, "namespace", "")]
}

# ── DIAGNOSTIC READS (both agents) ───────────────────────
allow if {
    object.get(input, "agent", "") in {"platform", "integration"}
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") in {"get", "describe", "logs", "top", "events"}
}

# ── PLATFORM (kubectl) ────────────────────────────────────

# kubectl rollout undo / restart
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "rollout"
    object.get(input, "subverb", "") in {"undo", "restart"}
    not namespace_forbidden
}

# kubectl scale — replicas 1-10
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "scale"
    replicas := object.get(input, "replicas", null)
    replicas != null
    to_number(replicas) >= 1
    to_number(replicas) <= 10
    not namespace_forbidden
}

# kubectl delete pod / job
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "delete"
    object.get(input, "resource", "") in {"pod", "pods", "job", "jobs"}
    not namespace_forbidden
}

# kubectl patch — blocked if patch modifies command/args
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "patch"
    object.get(input, "resource", "") in {
        "deployment", "deployments",
        "statefulset", "statefulsets",
        "daemonset", "daemonsets",
        "service", "services",
        "hpa", "horizontalpodautoscaler", "horizontalpodautoscalers",
        "cronjob", "cronjobs",
        "persistentvolumeclaim", "persistentvolumeclaims", "pvc",
        "resourcequota", "resourcequotas",
        "limitrange", "limitranges",
        "networkpolicy", "networkpolicies",
        "ingress", "ingresses",
        "configmap", "configmaps",
    }
    not namespace_forbidden
    patch := object.get(input, "patch_content", "")
    not contains(patch, "\"command\"")
    not contains(patch, "/command")
    not contains(patch, "\"args\"")
    not contains(patch, "/args")
}

# kubectl set image / env / resources
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "set"
    object.get(input, "subverb", "") in {"image", "env", "resources"}
    not namespace_forbidden
}

# kubectl create configmap / secret — missing resource fix
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "create"
    object.get(input, "resource", "") in {"configmap", "configmaps", "secret", "secrets"}
    not namespace_forbidden
}

# kubectl label / annotate
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") in {"label", "annotate"}
    not namespace_forbidden
}

# kubectl cordon / uncordon / drain (node)
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") in {"cordon", "uncordon", "drain"}
}

# kubectl apply — blocked if manifest modifies command/args
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "apply"
    not namespace_forbidden
    patch := object.get(input, "patch_content", "")
    not contains(patch, "\"command\"")
    not contains(patch, "/command")
    not contains(patch, "\"args\"")
    not contains(patch, "/args")
}

# ── INTEGRATION ───────────────────────────────────────────

jenkins_verbs := {"build-job", "cancel-job", "stop-job", "build"}

allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "jenkins-cli"
    jenkins_verbs[object.get(input, "verb", "")]
}

allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "psql"
}

allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "redis-cli"
}

allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "curl"
}

# ── Deny reasons (else chain — single value guaranteed) ───

_patch_touches_command_or_args(patch) if contains(patch, "\"command\"")
_patch_touches_command_or_args(patch) if contains(patch, "/command")
_patch_touches_command_or_args(patch) if contains(patch, "\"args\"")
_patch_touches_command_or_args(patch) if contains(patch, "/args")

deny_reason := "Empty or missing command" if {
    object.get(input, "command", "") == ""
} else := sprintf(
    "Protected namespace '%v': actions on system infrastructure are forbidden",
    [object.get(input, "namespace", "")]
) if {
    object.get(input, "command", "") != ""
    namespace_forbidden
} else := "Patch forbidden: modifying 'command' or 'args' replaces the application with a fake fix — the service appears UP but does nothing" if {
    object.get(input, "command", "") != ""
    not namespace_forbidden
    object.get(input, "verb", "") in {"patch", "apply"}
    _patch_touches_command_or_args(object.get(input, "patch_content", ""))
} else := sprintf(
    "Tool '%v' not authorized for agent '%v' (verb: '%v')",
    [object.get(input, "tool", ""), object.get(input, "agent", ""), object.get(input, "verb", "")]
) if {
    object.get(input, "command", "") != ""
    not namespace_forbidden
    not allow
}
