---
type: database
agent: Integration
---

# Runbook — Database Instance Unreachable or Refusing Connections

**Symptom**: Applications cannot connect to the database: **timeout**, **connection refused**, or **authentication failed** for all or most clients.

**Indicators**:
- Health checks fail; uptime monitors red.
- `telnet host 5432` or `nc -zv` fails from app network.
- Cloud provider shows instance **stopped**, **failed over**, or **maintenance**.

---

## Common Causes

1. **Instance down** — crash, maintenance window, failed AZ.
2. **Network** — security group, firewall, or service mesh rule changed.
3. **DNS / endpoint** — wrong hostname after failover; stale connection string in secret.
4. **TLS / cert** — rotation broke client trust.
5. **Auth** — password rotated in DB but not in Kubernetes Secret / Vault.

---

## Diagnosis Steps

```bash
# From a jump host or debug pod in same network as app
nc -zv <db-host> <port>
# or
curl -v telnet://<db-host>:<port>

# PostgreSQL client
psql "host=<db-host> port=<port> dbname=<db> user=<user> sslmode=require" -c 'select 1'
```

**Cloud / operator**:
- Verify instance status, **recent failover**, storage full, parameter group pending reboot.
- Check **subnet routing** and **private link** if used.

**Kubernetes**:
```bash
kubectl get secret <db-secret> -n <namespace> -o yaml   # decode base64 carefully
kubectl get endpoints -n <namespace>                   # if DB exposed via Service
```

---

## Remediation

### Failover or reboot in progress
- Wait for **stable primary** endpoint; update apps if DNS changed.
- Read-only replicas: redirect read traffic only if application supports it.

### Network / security group
- Restore rules allowing app subnets to DB port; least privilege CIDRs.

### Wrong credentials
- Sync password in DB and in **Secret**; rolling restart app **after** secret update.

### Storage full / crash loop
- Expand storage or purge WAL/archivelog per vendor runbook; involve DBA.

---

## Risk Level

- Read-only verification commands: **low**
- Failing over primary: **high** (data plane impact)
- Broad security group `0.0.0.0/0` to DB: **critical** — avoid

---

## Follow-up Actions

1. Document **RTO/RPO** and run **failover drill**.
2. Use **managed DNS** or operator that updates endpoint after failover.
3. Add synthetic check from app namespace to DB (not only from bastion).
