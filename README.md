# agent-llm — Multi-Agent Incident Remediation System

Autonomous system that receives alerts, analyzes them through multiple LLM agents, validates actions via OPA, and executes them via MCP.

## Architecture

```
Alert → Webhook (FastAPI :8000)
      → Kafka topic "incidents"
      → Consumer → LangGraph Pipeline
                     ├─ [observability]   LLM classification (platform / integration)
                     ├─ [check_cache]     Qdrant semantic cache
                     ├─ [platform]        K8s remediation plan (LLM + runbooks)
                     ├─ [integration]     Jenkins/DB remediation plan (LLM + runbooks)
                     ├─ [opa_validate]    OPA policy validation
                     ├─ [execute]         Execution via MCP
                     ├─ [audit]           Elasticsearch indexing
                     └─ [enrich_memory]   Qdrant memory + semantic cache
```

Agents can exchange data: if Platform needs Jenkins/DB state (or Integration needs K8s state), they request it from each other before building their plan. OPA validation supports up to `OPA_MAX_RETRIES` revision cycles before blocking and escalating.

## Prerequisites

- Python 3.11+
- Docker Desktop
- Ollama with `nomic-embed-text` model (`ollama pull nomic-embed-text`)
- Groq API key (https://console.groq.com)

## Quick Start

### 1. Start Docker services

```bash
docker compose up -d
```

Services: Elasticsearch, Kibana, Kafka, Zookeeper, Qdrant, OPA, Langfuse, PostgreSQL.

```bash
docker compose ps
```

### 2. Configure environment

```bash
cp .env .env.local
```

Required variables:

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq API key |
| `GROQ_MODEL` | Model to use (e.g. `openai/gpt-oss-120b`) |
| `OLLAMA_EMBED_MODEL` | Ollama embedding model (e.g. `nomic-embed-text`) |
| `ELASTICSEARCH_URL` | Elasticsearch URL (default: `http://localhost:9200`) |
| `QDRANT_URL` | Qdrant URL (default: `http://localhost:6333`) |
| `KAFKA_BROKER` | Kafka broker (default: `localhost:9092`) |
| `OPA_URL` | OPA URL (default: `http://localhost:8181`) |

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the system

```bash
python main.py
```

On startup, the system automatically:
- Checks Docker services
- Initializes Qdrant collections
- Creates the Kafka topic
- Initializes Elasticsearch indexes
- Loads 36 runbooks into RAG memory
- Starts the FastAPI webhook on `:8000`
- Starts the Kafka consumer

### 5. Test

```bash
python tests/simulate_alert.py
```

Interactive menu with 7 scenarios:
1. Platform only — CrashLoopBackOff
2. Integration only — DB connection exhausted
3. Shared state — Integration requests K8s data
4. Shared state — Platform requests DB data
5. OPA validation (approval)
6. OPA rejection + retry approval
7. OPA double rejection (block + escalation)

Or send an alert manually:

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

The webhook also accepts the native Alertmanager format (`{"alerts": [...]}`) and applies dedup + pre-check filtering.

## Tuning (.env variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_SCORE_THRESHOLD` | `0.80` | Minimum score for a semantic cache hit |
| `OPA_MAX_RETRIES` | `2` | Maximum OPA retry attempts before blocking |
| `CONSUMER_RETRY_DELAYS` | `2,5,10` | Delays (seconds) between consumer retries |
| `WEBHOOK_DEDUP_TTL_S` | `60` | Dedup window (seconds) per pod/namespace |
| `FINGERPRINT_TTL_S` | `300` | Suppression window after a successful resolution |
| `POST_CHECK_DELAY_S` | `30` | Delay before verifying remediation (real mode) |

## Observability

| Service | URL | Usage |
|---------|-----|-------|
| Kibana | http://localhost:5601 | Audit trail and incident visualization |
| Langfuse | http://localhost:3000 | LLM call tracing |
| Qdrant Dashboard | http://localhost:6333/dashboard | Vector collection inspection |

## Project Structure

```
agents/
  observability.py     Incident classification (platform / integration)
  platform_agent.py    K8s remediation plan
  integration_agent.py Jenkins/DB remediation plan
  opa_validator.py     OPA policy validation
  executor.py          Action execution via MCP
  memory_writer.py     Qdrant storage (memory + semantic cache)
  audit.py             Elasticsearch recording
  notifier.py          Operator escalation on definitive block
  memory.py            Semantic search — runbooks + cache
  llm_retry.py         Groq 429 retry with Retry-After backoff

orchestrator/
  graph.py             LangGraph pipeline (state machine + routing)
  consumer.py          Kafka consumer with dedup + fingerprint suppression
  state.py             AgentState TypedDict
  post_check.py        Post-remediation health verification (real mode)

kafka_bridge/
  webhook.py           FastAPI /alert endpoint (dedup + pre-check)
  producer.py          Kafka producer
  pre_check.py         Pre-publish pod health check

mcp/
  client.py            MCP dispatcher (mock / real mode)
  mock_data.py         Static mock data for local testing

k8s/
  prometheus_client.py     Logs (kubectl events) + metrics (Prometheus API)
  k8s_client.py            K8s state — pods, nodes, deployments (kubectl)
  kubectl_executor.py      Action execution via kubectl commands
  manifests/
    alertmanager-config.yaml  Alertmanager webhook → http://host.minikube.internal:8000/alert
    prometheus-rules.yaml     PrometheusRule for CrashLoopBackOff and OOMKilled alerts
  fixtures/
    crash-test.yaml      CrashLoopBackOff (busybox exit 1)
    oomkill-test.yaml    OOMKill (stress vs 50Mi limit)
    image-pull-test.yaml ImagePullBackOff
    probe-fail-test.yaml PodNotReady (readiness probe)

setup/
  seed_rag.py          Runbook loader into Qdrant
  runbooks/            36 Markdown runbooks (K8s, DB, Jenkins, network)

config/
  langfuse.py                LLM tracing instrumentation
  prompts.py                 Jinja2 prompt loader
  logger.py                  Structured logging setup
  remediation_policy.rego    OPA authorization policy

tests/
  simulate_alert.py    Interactive test scenarios
```

## Shutdown

```bash
# Stop Python system
Ctrl+C

# Stop Docker services
docker compose down
```

## MCP Mode

The system runs in mock mode by default (`MCP_MODE=mock`).

### Mock mode (default)

No external dependencies. Static data from `mcp/mock_data.py` is used for all agents.

### Real mode (minikube)

Connects to a live minikube cluster. Data collection uses `kubectl` and the Prometheus API; actions execute directly via `kubectl`. After each remediation, a post-check verifies the deployment is actually healthy before marking the incident resolved and writing to the semantic cache.

**Requirements:**
- minikube running (`minikube start`)
- Prometheus stack installed (e.g. `kube-prometheus-stack` via Helm)
- Prometheus port-forwarded: `kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090`

**Enable:**

```bash
# .env
MCP_MODE=real
PROMETHEUS_URL=http://localhost:9090
K8S_NAMESPACE=default
```

**Deploy test workloads:**

```bash
kubectl apply -f k8s/fixtures/crash-test.yaml      # CrashLoopBackOff
kubectl apply -f k8s/fixtures/oomkill-test.yaml    # OOMKill
kubectl apply -f k8s/fixtures/image-pull-test.yaml # ImagePullBackOff
kubectl apply -f k8s/fixtures/probe-fail-test.yaml # PodNotReady
```

**Configure Alertmanager:**

```bash
kubectl apply -f k8s/manifests/alertmanager-config.yaml
kubectl apply -f k8s/manifests/prometheus-rules.yaml
```

Alerts are sent to `http://host.minikube.internal:8000/alert` (your local webhook).
