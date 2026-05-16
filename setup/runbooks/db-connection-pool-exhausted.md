---
type: database
agent: Integration
---

# Runbook — Database Connection Pool Exhausted

**Symptom**: Application logs report **too many connections**, **pool exhausted**, or **timeout acquiring connection**. API latency spikes; errors like `FATAL: sorry, too many clients already` (PostgreSQL).

**Indicators**:
- Metrics: active connections near `max_connections` or pool `maxSize`.
- JDBC/Hikari/DBCP logs: `Connection is not available`, `Pool empty`.
- Similar alerts from PgBouncer or RDS Performance Insights.

---

## Common Causes

1. **Pool misconfiguration** — `maxPoolSize` per instance × replica count > DB limit.
2. **Connection leak** — code path does not close connections or return to pool.
3. **Traffic spike** — legitimate load without scaling or pool tuning.
4. **Long transactions** — connections held for minutes (batch job, lock).
5. **Thundering herd** — many pods restart and open pools simultaneously.

---

## Diagnosis Steps

**PostgreSQL example**:

```sql
-- Current connections by state and application
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;

-- Who holds connections (trim in prod)
SELECT pid, usename, application_name, client_addr, state, query_start, left(query, 80) AS query
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY query_start NULLS LAST;

-- Limit
SHOW max_connections;
```

**Application**:
- Confirm **one** DataSource per process; avoid creating per-request pools.
- Check **idle timeout** and **max lifetime** for pool settings vs DB `idle_in_transaction_session_timeout`.

---

## Remediation

### Immediate relief (coordination required)
- **Restart** leaking application pods/instances **after** identifying leak fix or short window (brief outage risk).
- If using **PgBouncer**: verify pool mode (`transaction` vs `session`) matches app expectations.

### Correct pool sizing
- Ensure `sum(max_pool_per_service_instance × instances) + admin_reserve < max_connections`.
- Lower per-instance `maxPoolSize` before scaling replicas out.

### Fix leaks
- Audit `try/finally` or language equivalents for connection/session close.
- For ORMs: ensure request-scoped sessions are disposed.

### Long queries / locks
- See `db-locks-and-blocking-queries.md`; kill or fix blocking sessions only with approval.

---

## Risk Level

- Tuning pool down: **low** if capacity still sufficient
- Bouncing all app instances: **medium**
- Raising `max_connections` without sizing RAM/CPU: **medium–high**

---

## Follow-up Actions

1. Add alerts at **80%** of `max_connections` and per-application breakdown.
2. Load test after pool changes.
3. For CI/CD: ensure integration tests close DB handles and use small pools.
