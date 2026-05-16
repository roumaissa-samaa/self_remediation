---
type: database
agent: Integration
---

# Runbook — Database Locks, Blocking Queries & Slow Transactions

**Symptom**: Queries hang; APIs time out; dashboards show **lock wait** or **long running queries**. Jenkins or batch jobs may stall waiting on DB.

**Indicators**:
- `pg_stat_activity` shows `wait_event_type = Lock` or long `query_start`.
- Monitoring shows **deadlocks** or **lock timeouts** in logs.
- CPU low but throughput collapsed (classic lock contention).

---

## Common Causes

1. **Missing index** — sequential scans + row locks on large updates.
2. **Long transaction** — open transaction idle in app holding locks.
3. **DDL during peak** — migration locks table (`ACCESS EXCLUSIVE`).
4. **Bad lock ordering** — deadlock between two workers.
5. **Orphaned prepared transaction** (rare) holding locks.

---

## Diagnosis Steps

**PostgreSQL**:

```sql
-- Blocking hierarchy (simplified)
SELECT blocked_locks.pid AS blocked_pid,
       blocking_locks.pid AS blocking_pid,
       blocked_activity.query AS blocked_query,
       blocking_activity.query AS blocking_query
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
  ON blocking_locks.locktype = blocked_locks.locktype
 AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
 AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
 AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
 AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
 AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
 AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
 AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
 AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
 AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
 AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;

-- Long running queries
SELECT pid, now() - query_start AS duration, state, wait_event_type, wait_event, left(query, 120)
FROM pg_stat_activity
WHERE state != 'idle' AND query_start IS NOT NULL
ORDER BY duration DESC
LIMIT 20;
```

---

## Remediation

### Safe first steps
- Identify **blocking** session: application name, user, query.
- Contact owning team; if runaway **report** or **analytics** query, cancel lower priority.

### Terminate session (destructive — approval required)

```sql
-- PostgreSQL: graceful then force if needed
SELECT pg_cancel_backend(<pid>);   -- cancel current query
-- SELECT pg_terminate_backend(<pid>);  -- last resort
```

### Application / schema
- Add or fix **indexes** for hot WHERE/JOIN columns.
- Split large batch updates; use **smaller transactions**.
- Schedule heavy **DDL** off-peak with lock timeout and retry.

### Deadlocks
- Fix **consistent lock order** in code; retry on deadlock where supported.

---

## Risk Level

- Read-only diagnostics: **low**
- `pg_cancel_backend` / `terminate`: **medium** (may lose in-flight work)
- Killing blocking migration: **high** — can leave schema inconsistent; follow migration playbook

---

## Follow-up Actions

1. Set **`lock_timeout`** and **`statement_timeout`** appropriately per role.
2. Log **slow queries** and review weekly.
3. For CI: avoid running destructive load tests against shared DB without isolation.
