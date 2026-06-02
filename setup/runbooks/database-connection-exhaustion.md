---
type: database
agent: Integration
---

# Runbook — Database Connection Exhaustion

**Symptom**: Database connections are close to `max_connections`, or applications report errors such as **too many connections**, **connection limit exceeded**, or **unable to acquire database connection**. This often results in increased latency, failed requests, and customer-facing outages.

**Indicators**:

* `count(*)` from `pg_stat_activity` approaches `max_connections`.
* Application logs contain errors like:

  * `FATAL: sorry, too many clients already`
  * `too many connections`
  * `timeout acquiring connection`
* Large number of connections in `idle in transaction` state.
* Connection pool metrics show saturation.

---

## Common Causes

1. **No connection pooler** — Applications connect directly to the database without PgBouncer or RDS Proxy.
2. **Pool sizing mismatch** — `pool_size × replicas` exceeds available database connections.
3. **Connection leak** — Connections or transactions are not properly closed and returned to the pool.
4. **Traffic spike** — Sudden increase in legitimate traffic exhausts available connections.
5. **Long-running transactions** — Connections remain occupied for extended periods.
6. **Recent deployment issue** — New application version introduces connection management bugs.

---

## Diagnosis Steps

### Confirm connection usage

```sql
-- Total active connections
SELECT count(*) FROM pg_stat_activity;

-- Database limit
SHOW max_connections;

-- Connections grouped by state
SELECT state, count(*)
FROM pg_stat_activity
GROUP BY state;
```

### Identify problematic sessions

```sql
SELECT
    pid,
    usename,
    application_name,
    client_addr,
    state,
    state_change,
    query_start,
    LEFT(query, 100) AS query
FROM pg_stat_activity
ORDER BY state_change;
```

### Check for connection leaks

Look specifically for a large number of:

```text
idle in transaction
```

connections, especially those persisting for several minutes. This is a strong indicator of unclosed transactions or application-side connection leaks.

### Review pool configuration

Verify:

```text
pool_size × number_of_replicas < max_connections
```

with sufficient headroom for:

* Administrative connections
* Monitoring tools
* Maintenance operations

---

## Remediation

### Immediate Mitigation

#### Terminate stale idle transactions

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND now() - state_change > interval '10 minutes';
```

**Caution:** This may roll back uncommitted work.

#### Restart the leaking service

If a recent deployment introduced the leak:

1. Identify the service owning the excessive connections.
2. Restart the affected instances.
3. Monitor connection counts after restart.
4. Roll back the deployment if the issue reappears.

#### Reduce connection pressure

* Temporarily reduce incoming traffic using rate limiting.
* Scale read replicas and redirect read-only workloads.
* Pause non-critical batch jobs or background workers consuming connections.

### Root-Cause Remediation

#### Deploy a connection pooler

Implement a database connection proxy such as:

* **PgBouncer**
* **Amazon RDS Proxy**

This is the most durable fix for connection exhaustion issues.

#### Correct pool sizing

Ensure:

```text
(sum of all service pool sizes) + reserve connections < max_connections
```

Example:

```text
5 replicas × 20 connections = 100
Database max_connections = 150
Reserve = 20

100 + 20 < 150 ✓
```

Reduce per-instance pool sizes before increasing application replicas.

#### Fix connection leaks

Review application code for:

* Missing connection close operations.
* Unclosed transactions.
* ORM sessions not being disposed.
* Missing `finally`, `defer`, or equivalent cleanup blocks.

#### Address long-running transactions

Investigate transactions that remain open for several minutes:

```sql
SELECT pid,
       usename,
       application_name,
       now() - xact_start AS transaction_age,
       state,
       query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY transaction_age DESC;
```

Optimize or terminate problematic transactions after obtaining approval.

---

## Prevention

### Connection Pooling

* Place PgBouncer or RDS Proxy in front of the database.
* Use transaction pooling where application compatibility allows.

### Capacity Planning

Maintain connection headroom:

```text
replicas × pool_size ≤ 70–80% of max_connections
```

Reserve capacity for:

* Monitoring
* Administrative access
* Maintenance jobs
* Failover scenarios

### Monitoring & Alerting

Create alerts for:

* Connections > 80% of `max_connections`
* Excessive `idle in transaction` sessions
* Connection acquisition latency
* Pool utilization > 80%
* Pool exhaustion events

### Testing

* Include connection-leak detection in integration tests.
* Perform load testing after pool-size changes.
* Validate connection behavior after deployments.

---

## Risk Level

| Action                                                 | Risk        |
| ------------------------------------------------------ | ----------- |
| Terminating stale idle transactions                    | Low–Medium  |
| Restarting leaking application instances               | Medium      |
| Reducing pool size                                     | Low         |
| Scaling read replicas                                  | Low         |
| Increasing `max_connections` without resource analysis | Medium–High |

---

## Follow-up Actions

1. Deploy a connection pooler if one is not already present.
2. Add connection-budget documentation for every service.
3. Review pool sizing whenever replica counts change.
4. Investigate all occurrences of `idle in transaction`.
5. Load-test the platform under peak expected traffic.
6. Add SLO alerts for pool saturation and connection exhaustion.
