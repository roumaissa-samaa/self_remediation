---
type: ci-cd
agent: Integration
---

# Runbook — CI/CD Artifacts, Registry & Dependency Failures

**Symptom**: Pipeline fails before or after tests, during **image build**, **push**, or **dependency download** (not specific to Jenkins UI).

**Indicators**:
- `docker push` / `buildah push` returns 401, 403, 429, or TLS errors.
- `npm ci`, `pip install`, `mvn`, `gradle` report 5xx or checksum failures.
- Helm chart or OCI artifact pull fails in deploy stage.

---

## Common Causes

1. **Registry authentication** — expired robot account, wrong `docker config` on agent.
2. **Rate limiting** — Docker Hub, npm, PyPI throttling anonymous or CI IPs.
3. **Proxy / TLS inspection** — corporate proxy breaks HTTPS; custom CA not trusted on agent.
4. **Artifact immutability** — pushing same tag twice rejected.
5. **Storage full** on registry or agent cache volume.

---

## Diagnosis Steps

```bash
# From Jenkins agent (or equivalent CI worker)
docker login <registry>   # verify interactively only on debug agent
echo $HTTP_PROXY $HTTPS_PROXY

# Test pull without cache
docker pull <image>:<tag>

# npm example
npm config get registry
npm ping

# pip example
pip install -v <package>==<version> 2>&1 | tail -50
```

Check job configuration: **secret binding**, **config files**, and **environment** for `DOCKER_*`, `NPM_*`, `PIP_*`.

---

## Remediation

### Auth / 401 / 403
- Refresh registry credentials; use short-lived tokens with scoped permissions.
- Ensure same credentials are available in **pipeline** and **kubernetes pull secrets** if deploy pulls private images.

### Rate limits / 429
- Use **pull-through cache** or **mirror**; authenticate even for public pulls.
- Vendor dependencies or use internal artifact repository (Artifactory, Nexus, GitLab registry).

### TLS / proxy
- Install corporate root CA on agent image; set `SSL_CERT_FILE` if required.
- Whitelist registry and package hosts on proxy.

### Immutable tag conflict
- Use **unique tags** per build (`git sha`, build number); never reuse `latest` for releases.

---

## Risk Level

- Fixing cache/registry config: **low**
- Disabling TLS verify globally: **high** (never do in production)
- Sharing broad registry credentials across all jobs: **high**

---

## Follow-up Actions

1. Standardize agent image with pre-installed CA and tool versions.
2. Document **required** outbound URLs for firewall requests.
3. Scan images in registry after push (policy in OPA / admission can complement).
