# agent-llm — Autonomous Incident Remediation System

A multi-agent LLM platform that receives infrastructure alerts, diagnoses root causes through specialized agents, validates remediation actions via policy enforcement, and executes fixes autonomously — with full audit trail and semantic memory.

---

## How it works

```
Alert (Alertmanager / curl)
  │
  ▼
FastAPI Webhook :8000          ← dedup + pre-check filtering
  │
  ▼
Kafka topic "incidents"
  │
  ▼
LangGraph Pipeline
  ├── [observability]     LLM classification → platform | integration
  ├── [platform]          K8s remediation plan  (LLM + runbooks + shared state)
  ├── [integration]       Jenkins/DB plan        (LLM + runbooks + shared state)
  ├── [opa_validate]      Policy check — approve | revise (up to OPA_MAX_RETRIES)
  ├── [execute]           MCP dispatcher (mock or real kubectl)
  ├── [audit]             Elasticsearch indexing
  └── [enrich_memory]     Qdrant — incident memory + semantic cache
```

**Agent-to-agent coordination:** Platform and Integration agents can request data from each other before building their plan — Platform can ask for Jenkins/DB state, Integration can ask for K8s state. This produces more accurate cross-system remediation plans.

**OPA governance:** Every generated action set goes through policy validation. On rejection, the agent revises the plan. After `OPA_MAX_RETRIES` failed attempts, the system escalates to the operator.

---

## Stack

| Layer | Technology |
|-------|-----------|
| LLM & Orchestration | LangGraph, Groq (llama-3.3-70b), LangChain |
| Embeddings | Ollama (`nomic-embed-text`) |
| Vector DB | Qdrant (runbooks, semantic cache, memory) |
| Message Broker | Kafka + Zookeeper |
| Policy Engine | OPA (Open Policy Agent) |
| Audit | Elasticsearch + Kibana |
| LLM Tracing | Langfuse |
| Tool Protocol | MCP (Model Context Protocol) |
| API | FastAPI + Uvicorn |
| K8s Client | Python kubernetes SDK + kubectl |

---

## Prerequisites

- Python 3.11+
- Docker Desktop
- Ollama with `nomic-embed-text`: `ollama pull nomic-embed-text`
- Groq API key — [console.groq.com](https://console.groq.com)

---

## Quick Start

### 1. Start infrastructure

```bash
docker compose up -d
docker compose ps
```

Services started: Elasticsearch, Kibana, Kafka, Zookeeper, Qdrant, OPA, Langfuse, PostgreSQL.

### 2. Configure environment

```bash
cp .env .env.local
```

Minimum required variables:

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` | e.g. `llama-3.3-70b-versatile` |
| `OLLAMA_EMBED_MODEL` | e.g. `nomic-embed-text` |
| `ELASTICSEARCH_URL` | default `http://localhost:9200` |
| `QDRANT_URL` | default `http://localhost:6333` |
| `KAFKA_BROKER` | default `localhost:9092` |
| `OPA_URL` | default `http://localhost:8181` |

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the system

```bash
python main.py
```

On startup the system automatically:
- Validates Docker services are reachable
- Initializes 3 Qdrant collections: `documents`, `memory`, `semantic_cache`
- Creates Kafka topic `incidents`
- Creates Elasticsearch indices: `incidents`, `audit_trail`, `documents`
- Seeds RAG with 36 runbooks (skipped if already loaded)
- Starts MCP server on `:8001` (real mode only)
- Starts FastAPI webhook on `:8000`
- Starts Kafka consumer (blocking loop)

### 5. Send a test alert

```bash
python tests/simulate_alert.py
```

Interactive menu with 7 scenarios:
1. Platform only — CrashLoopBackOff (K8s)
2. Integration only — DB connection pool exhausted
3. Shared state — Integration requests K8s data from Platform
4. Shared state — Platform requests DB data from Integration
5. OPA validation — first-attempt approval
6. OPA rejection + revision → approval
7. OPA double rejection → definitive block + escalation

Or send an alert directly:

```bash
curl -X POST http://localhost:8000/alert \
  -H "Content-Type: application/json" \
  -d '{
    "alertname": "PodCrashLoopBackOff",
    "service": "api-gateway",
    "namespace": "production",
    "message": "Pod restarted 12 times in 10 minutes",
    "source": "alertmanager"
  }'
```

The webhook accepts both the simplified format above and the native Alertmanager payload (`{"alerts": [...]}`).

### 6. Shutdown

```bash
# Stop Python processes
Ctrl+C

# Stop infrastructure
docker compose down
```

---

## MCP Mode

Controlled by `MCP_MODE` in `.env`.

### Mock (default)

No external cluster needed. All K8s, Jenkins, and DB data is served from `mcp_layer/mock_data.py`. Suitable for development and testing.

### Real (minikube)

Connects to a live Kubernetes cluster. Data collection uses `kubectl` and the Prometheus API; actions are executed via `kubectl`. After each remediation, a post-check waits `POST_CHECK_DELAY_S` seconds and verifies pod health before marking the incident resolved.

**Requirements:**
- minikube running: `minikube start`
- Prometheus stack installed (e.g. via `kube-prometheus-stack` Helm chart)
- Prometheus port-forwarded: `kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090`

**Enable:**

```env
MCP_MODE=real
PROMETHEUS_URL=http://localhost:9090
K8S_NAMESPACE=default
```

**Deploy test workloads:**

```bash
kubectl apply -f k8s/fixtures/crash-test.yaml       # CrashLoopBackOff
kubectl apply -f k8s/fixtures/oomkill-test.yaml     # OOMKill
kubectl apply -f k8s/fixtures/image-pull-test.yaml  # ImagePullBackOff
kubectl apply -f k8s/fixtures/probe-fail-test.yaml  # PodNotReady (readiness probe)
```

**Wire Alertmanager:**

```bash
kubectl apply -f k8s/manifests/alertmanager-config.yaml
kubectl apply -f k8s/manifests/prometheus-rules.yaml
```

Alerts are forwarded to `http://host.minikube.internal:8000/alert`.

---

## Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_SCORE_THRESHOLD` | `0.80` | Minimum similarity score for a semantic cache hit |
| `OPA_MAX_RETRIES` | `2` | Revision attempts before definitive block |
| `CONSUMER_RETRY_DELAYS` | `2,5,10` | Seconds between consumer retry attempts |
| `WEBHOOK_DEDUP_TTL_S` | `60` | Dedup window per pod/namespace (seconds) |
| `FINGERPRINT_TTL_S` | `300` | Suppression window after successful resolution (seconds) |
| `POST_CHECK_DELAY_S` | `30` | Wait before post-remediation health check (real mode) |

---

## Observability

| Service | URL | Purpose |
|---------|-----|---------|
| Kibana | http://localhost:5601 | Audit trail, incident timelines |
| Langfuse | http://localhost:3000 | LLM call tracing and analytics |
| Qdrant Dashboard | http://localhost:6333/dashboard | Vector collection inspection |

---

## CI/CD

GitHub Actions builds and pushes to Docker Hub on every merge to `main` and on version tags (`v*.*.*`).

```bash
# Pull the latest image
docker pull roumaissa1209/ai-self-remediation:latest
```

Tags:
- `latest` — tip of main
- `vX.Y.Z` — semantic version tags
- `<short-sha>` — PR and branch builds

---

## Project Structure

```
agents/
  observability.py      Incident classification → platform | integration
  platform_agent.py     K8s remediation plan builder
  integration_agent.py  Jenkins/DB remediation plan builder
  opa_validator.py      OPA policy validation + retry routing
  executor.py           Action execution via MCP dispatcher
  memory_writer.py      Qdrant storage (memory + semantic cache)
  audit.py              Elasticsearch audit recording
  notifier.py           Operator escalation on definitive OPA block
  memory.py             Semantic search — runbooks + cache
  llm_retry.py          Groq 429 retry with Retry-After backoff

orchestrator/
  graph.py              LangGraph state machine + conditional routing
  consumer.py           Kafka consumer — dedup + fingerprint suppression
  state.py              AgentState TypedDict (full pipeline schema)
  post_check.py         Post-remediation health verification (real mode)

kafka_bridge/
  webhook.py            FastAPI /alert endpoint — dedup + pre-check
  producer.py           Kafka producer (acks=all, 3 retries)
  pre_check.py          Pre-publish pod health gate

mcp_layer/
  client.py             MCP dispatcher — mock | real
  mock_data.py          Static K8s/Jenkins/DB data for local testing

mcp_server.py           Standalone MCP SSE server (:8001) for real mode

k8s/
  prometheus_client.py  Logs (kubectl events) + metrics (Prometheus API)
  k8s_client.py         K8s state — pods, nodes, deployments
  kubectl_executor.py   Action execution via kubectl subprocess
  manifests/            Alertmanager config + Prometheus rules
  fixtures/             Test workload manifests (crash, oom, imagepull, probe)

setup/
  seed_rag.py           Runbook loader into Qdrant
  runbooks/             36 Markdown runbooks (K8s, Jenkins, DB, OpenShift)

config/
  prompts.py            Jinja2 prompt loader (7 templates)
  logger.py             Structured JSON logging
  langfuse.py           LLM tracing instrumentation
  remediation_policy.rego  OPA authorization policy

prompts/
  observability.j2      Classification prompt
  platform_normal.j2    K8s plan (no shared state)
  platform_shared.j2    K8s plan (with Jenkins/DB context)
  platform_revision.j2  K8s plan revision after OPA rejection
  integration_normal.j2 Jenkins/DB plan (no shared state)
  integration_shared.j2 Jenkins/DB plan (with K8s context)
  integration_revision.j2  Jenkins/DB plan revision after OPA rejection

tests/
  simulate_alert.py     Interactive test runner (7 scenarios)
```

---

## OPA Policy

Actions are validated against `config/remediation_policy.rego` before execution.

**Allowed kubectl actions:** `rollout undo/restart`, `scale` (1–10 replicas), `delete pod`, `patch deployment`, `drain node`, `apply`

**Forbidden namespaces:** `kube-system`, `cert-manager`, `monitoring`, `ingress-nginx`

**Allowed Jenkins actions:** `build-job`, `cancel-job`, `stop-job`

**Allowed DB/API actions:** `psql`, `redis-cli`, `curl`

On rejection, the blocking agent receives the denial reason and revises its plan. After `OPA_MAX_RETRIES` rejections, the incident is escalated via the notifier (Teams webhook or logs).
