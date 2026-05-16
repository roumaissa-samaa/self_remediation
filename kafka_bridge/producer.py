from kafka import KafkaProducer
from kafka.errors import KafkaError
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

def publish_incident(payload: dict):
    future = producer.send("incidents", value=payload)
    try:
        future.get(timeout=10)
        print(f"Incident publie sur Kafka : {payload['incident_id']}")
    except KafkaError as e:
        print(f"[ERREUR] Kafka publish echoue : {e}")
        raise
