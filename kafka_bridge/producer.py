from kafka import KafkaProducer
from kafka.errors import KafkaError
from config.circuit_breaker import get_breaker
import json
import os
from dotenv import load_dotenv

load_dotenv(override=True)

producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BROKER"),
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    retries=3,
    request_timeout_ms=10000,
    acks="all",
)

_cb = get_breaker("kafka", failure_threshold=3, recovery_timeout=30.0)


def _send(payload: dict):
    future = producer.send("incidents", value=payload)
    future.get(timeout=10)


def publish_incident(payload: dict):
    try:
        _cb.call(_send, payload)
        print(f"Incident published to Kafka: {payload['incident_id']}")
    except KafkaError as e:
        print(f"[ERROR] Kafka publish failed: {e}")
        raise
    except RuntimeError as e:
        print(f"[ERROR] Kafka circuit breaker open — incident dropped: {e}")
        raise
