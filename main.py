import os
import sys
import signal
import subprocess
import threading
import time
import socket
from dotenv import load_dotenv

load_dotenv()


def free_port(port: int):
    """Kill any process occupying the given port (Windows)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True
        )
        pids = set()
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"],
                           capture_output=True)
            print(f"  Port {port} freed (PID {pid})")
    except Exception:
        pass


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def check_services():
    import requests
    services = [
        ("http://localhost:9200",             "Elasticsearch"),
        ("http://localhost:6333/collections", "Qdrant"),
        ("http://localhost:8181/v1/policies", "OPA"),
        ("http://localhost:3000",             "Langfuse"),
    ]
    print("\nChecking Docker services...")
    all_ok = True
    for url, name in services:
        try:
            requests.get(url, timeout=3)
            print(f"  OK  {name}")
        except Exception:
            print(f"  ERROR  {name} not reachable")
            all_ok = False
    return all_ok

def init_qdrant():
    print("\nInitialising Qdrant collections...")
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    client = QdrantClient(url=os.getenv("QDRANT_URL"))
    for name in ["memory", "documents", "semantic_cache"]:
        try:
            client.get_collection(name)
            print(f"  OK  Collection '{name}' already exists")
        except Exception:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE)
            )
            print(f"  OK  Collection '{name}' created")

def init_kafka():
    print("\nInitialising Kafka topic...")
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError
    import os
    try:
        admin = KafkaAdminClient(
            bootstrap_servers=os.getenv("KAFKA_BROKER"),
            request_timeout_ms=5000
        )
        topic = NewTopic(name="incidents", num_partitions=1, replication_factor=1)
        admin.create_topics([topic])
        print("  OK  Topic 'incidents' created")
        admin.close()
    except TopicAlreadyExistsError:
        print("  OK  Topic 'incidents' already exists")
    except Exception as e:
        print(f"  WARN  Kafka admin: {e}")


_ES_MAPPINGS = {
    "incidents": {
        "mappings": {
            "properties": {
                "incident_id":   {"type": "keyword"},
                "alertname":     {"type": "keyword"},
                "service":       {"type": "keyword"},
                "namespace":     {"type": "keyword"},
                "incident_type": {"type": "keyword"},
                "incident_cause":{"type": "text"},
                "resolved":      {"type": "boolean"},
                "timestamp":     {"type": "date"},
                "message":       {"type": "text"},
            }
        }
    },
    "audit_trail": {
        "mappings": {
            "properties": {
                "incident_id":   {"type": "keyword"},
                "action":        {"type": "keyword"},
                "agent":         {"type": "keyword"},
                "target":        {"type": "keyword"},
                "namespace":     {"type": "keyword"},
                "status":        {"type": "keyword"},
                "timestamp":     {"type": "date"},
                "reason":        {"type": "text"},
            }
        }
    },
    "documents": {
        "mappings": {
            "properties": {
                "title":         {"type": "text"},
                "content":       {"type": "text"},
                "incident_type": {"type": "keyword"},
                "agent":         {"type": "keyword"},
                "timestamp":     {"type": "date"},
            }
        }
    },
}

def init_elasticsearch():
    print("\nInitialising Elasticsearch indices...")
    from elasticsearch import Elasticsearch
    es_url = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    es = Elasticsearch(es_url)
    if not es.ping():
        raise ConnectionError(
            f"Elasticsearch not reachable at {es_url}. "
            "Make sure the service is running (docker compose up -d)."
        )
    print("  OK  Elasticsearch connection established")
    for index, body in _ES_MAPPINGS.items():
        if es.indices.exists(index=index):
            print(f"  OK  Index '{index}' already exists")
        else:
            es.indices.create(index=index, body=body)
            print(f"  OK  Index '{index}' created with mapping")

def init_rag():
    print("\nChecking RAG memory...")
    from qdrant_client import QdrantClient
    client = QdrantClient(url=os.getenv("QDRANT_URL"))
    count = client.count(collection_name="documents")
    if count.count > 0:
        print(f"  OK  RAG already populated ({count.count} documents)")
    else:
        print("  Seeding RAG with historical incidents...")
        from setup.seed_rag import seed
        seed()

def start_mcp_server():
    print("\nStarting MCP server on port 8001...")
    subprocess.run([
        sys.executable, "mcp_server.py",
    ])


def start_webhook():
    print("\nStarting FastAPI webhook on port 8000...")
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "kafka_bridge.webhook:app",
        "--port", "8000",
        "--log-level", "warning"
    ])

def start_consumer():
    print("\nStarting Kafka consumer...")
    from orchestrator.consumer import start_consumer
    start_consumer()

def _handle_sigterm(sig, frame):
    raise KeyboardInterrupt("SIGTERM received")

signal.signal(signal.SIGTERM, _handle_sigterm)

if __name__ == "__main__":
    print("=" * 55)
    print("Multi-Agent System — Incident Remediation")
    print("=" * 55)

    if not check_services():
        print("\nStart services first: docker compose up -d")
        sys.exit(1)

    init_qdrant()

    init_kafka()

    init_elasticsearch()

    init_rag()

    mcp_mode = os.getenv("MCP_MODE", "mock")
    if mcp_mode == "real":
        if not is_port_free(8001):
            print("\nPort 8001 in use — freeing it...")
            free_port(8001)
            time.sleep(1)
        mcp_thread = threading.Thread(target=start_mcp_server, daemon=True)
        mcp_thread.start()
        time.sleep(2)
        print("  OK  MCP server running on port 8001")

    if not is_port_free(8000):
        print("\nPort 8000 in use — freeing it...")
        free_port(8000)
        time.sleep(1)

    webhook_thread = threading.Thread(
        target=start_webhook,
        daemon=True
    )
    webhook_thread.start()
    time.sleep(2)

    print("\n" + "=" * 55)
    print("  System ready — Waiting for incidents")
    print("  Webhook : http://localhost:8000")
    if mcp_mode == "real":
        print("  MCP     : http://localhost:8001/sse")
    print("  Test    : python tests/simulate_alert.py")
    print("=" * 55 + "\n")

    start_consumer()