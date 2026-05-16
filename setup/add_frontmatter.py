from pathlib import Path

RUNBOOKS_DIR = Path(__file__).resolve().parent / "runbooks"

MAPPING: dict[str, tuple[str, str]] = {
    "config_errors":                    ("kubernetes", "Platform"),
    "crashloopbackoff":                 ("kubernetes", "Platform"),
    "deployment-stuck":                 ("kubernetes", "Platform"),
    "dns-failure":                      ("kubernetes", "Platform"),
    "helm-failed":                      ("kubernetes", "Platform"),
    "high-cpu":                         ("kubernetes", "Platform"),
    "imagepullbackoff":                 ("kubernetes", "Platform"),
    "ingress-errors":                   ("kubernetes", "Platform"),
    "init-container-failure":           ("kubernetes", "Platform"),
    "liveness-probe-failure":           ("kubernetes", "Platform"),
    "memory_leaks":                     ("kubernetes", "Platform"),
    "networkpolicy-blocking":           ("kubernetes", "Platform"),
    "node-diskpressure":                ("kubernetes", "Platform"),
    "node-notready":                    ("kubernetes", "Platform"),
    "oomkilled":                        ("kubernetes", "Platform"),
    "openshift-route":                  ("kubernetes", "Platform"),
    "openshift-scc":                    ("kubernetes", "Platform"),
    "pod-evicted":                      ("kubernetes", "Platform"),
    "pod-not-ready":                    ("kubernetes", "Platform"),
    "pod-pending":                      ("kubernetes", "Platform"),
    "pod-terminating-stuck":            ("kubernetes", "Platform"),
    "pvc-not-bound":                    ("kubernetes", "Platform"),
    "rbac-denied":                      ("kubernetes", "Platform"),
    "resource-quota-exceeded":          ("kubernetes", "Platform"),
    "service-unavailable":              ("kubernetes", "Platform"),
    "volume-full":                      ("kubernetes", "Platform"),
    "volume-mount-error":               ("kubernetes", "Platform"),

    "web_crashloopbackoff":             ("web", "Platform"),
    "web_imagepullbackoff":             ("web", "Platform"),
    "web_openshift_errors":             ("web", "Platform"),

    "ci-cd-artifacts-and-registry":     ("ci-cd", "Integration"),
    "jenkins-build-timeout-and-queue":  ("ci-cd", "Integration"),
    "jenkins-pipeline-failed":          ("ci-cd", "Integration"),

    "db-connection-pool-exhausted":     ("database", "Integration"),
    "db-instance-unreachable":          ("database", "Integration"),
    "db-locks-and-blocking-queries":    ("database", "Integration"),
}


def add_frontmatter():
    files = sorted(RUNBOOKS_DIR.glob("*.md"))
    updated = skipped = unknown = 0

    for path in files:
        stem = path.stem
        content = path.read_text(encoding="utf-8", errors="ignore")

        if content.startswith("---"):
            skipped += 1
            continue

        if stem not in MAPPING:
            print(f"  [INCONNU] {path.name} — non presente dans le mapping, ignoree")
            unknown += 1
            continue

        inc_type, agent = MAPPING[stem]
        frontmatter = f"---\ntype: {inc_type}\nagent: {agent}\n---\n\n"
        path.write_text(frontmatter + content, encoding="utf-8")
        print(f"  [OK] {path.name} -> type={inc_type}, agent={agent}")
        updated += 1

    print(f"\nTermine — {updated} mis a jour, {skipped} deja traites, {unknown} inconnus")


if __name__ == "__main__":
    add_frontmatter()
