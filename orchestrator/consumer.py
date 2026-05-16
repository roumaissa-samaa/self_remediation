from kafka import KafkaConsumer
import json
import os
import time
import logging
import traceback
from dotenv import load_dotenv
from orchestrator.graph import run_pipeline
from orchestrator.post_check import verify_remediation
from agents.audit import update_audit_resolved
from agents.memory_writer import write_to_cache

_SEP = "═" * 58

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

# Reduce noise from Kafka internal logs
logging.getLogger("kafka").setLevel(logging.WARNING)

_MAX_RETRIES       = 3
_RETRY_DELAYS      = [int(x.strip()) for x in os.getenv("CONSUMER_RETRY_DELAYS", "2,5,10").split(",")]
# How long to suppress re-fires of the same alert after a successful resolution
_FINGERPRINT_TTL   = float(os.getenv("FINGERPRINT_TTL_S", "300"))

_seen_ids: set[str] = set()
_active_fingerprints: set[str] = set()
_resolved_fingerprints: dict[str, float] = {}   # fingerprint → resolved_at timestamp


def _deployment_name(service: str) -> str:
    parts = service.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-2])
    return service


def _fingerprint(incident: dict) -> str:
    return "{}:{}".format(
        _deployment_name(incident.get("service", "")),
        incident.get("namespace", "default"),
    )


def _process_incident(incident: dict) -> None:
    incident_id = incident.get("incident_id", "unknown")
    fp          = _fingerprint(incident)
    now         = time.time()

    if incident_id in _seen_ids:
        logger.warning("Incident %s already processed — duplicate ignored", incident_id)
        return

    if fp in _active_fingerprints:
        logger.warning(
            "Incident %s skipped — [%s] is already being processed", incident_id, fp
        )
        return

    if fp in _resolved_fingerprints:
        age = now - _resolved_fingerprints[fp]
        if age < _FINGERPRINT_TTL:
            logger.warning(
                "Incident %s skipped — [%s] was resolved %.0fs ago (suppression window: %gs)",
                incident_id, fp, age, _FINGERPRINT_TTL,
            )
            return
        # TTL expired — allow re-processing (alert may have re-fired for real)
        del _resolved_fingerprints[fp]

    _active_fingerprints.add(fp)
    last_error: Exception | None = None

    try:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                final_state = run_pipeline(incident)
                _seen_ids.add(incident_id)
                logger.info("Incident %s processed successfully (attempt %d)", incident_id, attempt)
                exec_st = (final_state or {}).get("execution", {})
                comm_st = (final_state or {}).get("comm", {})
                opa_st  = (final_state or {}).get("opa", {})
                plan    = exec_st.get("remediation_plan", [])
                agent   = comm_st.get("active_agent", "?")
                n_ok    = sum(1 for r in (exec_st.get("execution_result") or []) if r.get("status") == "success")

                confirmed = verify_remediation(
                    incident.get("service", ""),
                    incident.get("namespace", "default"),
                    incident_id,
                )

                update_audit_resolved(incident_id, confirmed)
                if confirmed:
                    write_to_cache(final_state)

                print(f"\n{_SEP}")
                if confirmed:
                    print(f"  RESULT  →  ✓ RESOLVED  |  Agent: {agent}  |  {n_ok}/{len(plan)} actions OK")
                else:
                    print(f"  RESULT  →  ✗ UNRESOLVED  |  Agent: {agent}  |  post-check FAILED")
                print(f"{_SEP}\n")

                if confirmed and fp not in _resolved_fingerprints:
                    _resolved_fingerprints[fp] = time.time()
                elif not confirmed and fp in _resolved_fingerprints:
                    del _resolved_fingerprints[fp]
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Incident %s — attempt %d/%d failed: %s\n%s",
                    incident_id, attempt, _MAX_RETRIES, exc, traceback.format_exc()
                )
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[attempt - 1]
                    logger.info("Retrying in %ds...", delay)
                    time.sleep(delay)

        logger.error(
            "Incident %s ABANDONED after %d attempts. Last error: %s | Payload: %s",
            incident_id, _MAX_RETRIES, last_error,
            json.dumps(incident, ensure_ascii=False)
        )
    finally:
        _active_fingerprints.discard(fp)


def start_consumer():
    consumer = KafkaConsumer(
        "incidents",
        bootstrap_servers=os.getenv("KAFKA_BROKER"),
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        group_id="agent-llm-group",
        auto_offset_reset="latest"
    )

    logger.info("Kafka consumer started — waiting for incidents...")

    try:
        for message in consumer:
            incident = message.value
            logger.info("Incident received: %s", incident.get("incident_id", "unknown"))
            _process_incident(incident)
    except KeyboardInterrupt:
        logger.info("Stop requested — closing consumer...")
    finally:
        consumer.close()
        logger.info("Kafka consumer closed.")


if __name__ == "__main__":
    start_consumer()
