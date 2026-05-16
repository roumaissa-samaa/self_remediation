package remediation

default allow = false
default deny_reason = "Commande non autorisee par la politique remediation"

# ── Namespaces proteges ───────────────────────────────────
protected_namespaces := {"kube-system", "cert-manager", "monitoring", "ingress-nginx"}

namespace_forbidden if {
    protected_namespaces[object.get(input, "namespace", "")]
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

# kubectl delete pod only (not deployment / namespace)
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "delete"
    object.get(input, "resource", "") in {"pod", "pods"}
    not namespace_forbidden
}

# kubectl patch deployment
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "patch"
    object.get(input, "resource", "") in {"deployment", "deployments"}
    not namespace_forbidden
}

# kubectl drain node
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "drain"
}

# kubectl apply
allow if {
    object.get(input, "agent", "") == "platform"
    object.get(input, "tool", "") == "kubectl"
    object.get(input, "verb", "") == "apply"
    not namespace_forbidden
}

# ── INTEGRATION ───────────────────────────────────────────

jenkins_verbs := {"build-job", "cancel-job", "stop-job", "build"}

# jenkins-cli operations
allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "jenkins-cli"
    jenkins_verbs[object.get(input, "verb", "")]
}

# psql database operations
allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "psql"
}

# redis-cli cache operations
allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "redis-cli"
}

# curl for service API calls
allow if {
    object.get(input, "agent", "") == "integration"
    object.get(input, "tool", "") == "curl"
}

# ── Deny reasons ──────────────────────────────────────────

deny_reason := "Commande vide ou absente" if {
    object.get(input, "command", "") == ""
}

deny_reason := sprintf(
    "Namespace protege '%v' : actions interdites sur l infrastructure systeme",
    [object.get(input, "namespace", "")]
) if {
    object.get(input, "command", "") != ""
    namespace_forbidden
}

deny_reason := sprintf(
    "Outil '%v' non autorise pour l agent '%v' (verbe: '%v')",
    [object.get(input, "tool", ""), object.get(input, "agent", ""), object.get(input, "verb", "")]
) if {
    object.get(input, "command", "") != ""
    not namespace_forbidden
    not allow
}
