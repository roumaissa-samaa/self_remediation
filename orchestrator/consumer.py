import re

from kafka import KafkaConsumer
import json
import os
import time
import logging
import traceback
from dotenv import load_dotenv
from orchestrator.graph import run_pipeline

_SEP = "═" * 58

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

logging.getLogger("kafka").setLevel(logging.WARNING)

_MAX_RETRIES     = 3
_RETRY_DELAYS    = [int(x.strip()) for x in os.getenv("CONSUMER_RETRY_DELAYS", "2,5,10").split(",")]
_FINGERPRINT_TTL = float(os.getenv("FINGERPRINT_TTL_S", "300"))
_STATE_FILE      = os.getenv("CONSUMER_STATE_FILE", ".consumer_state.json")

_seen_ids: set[str] = set()
_active_fingerprints: set[str] = set()
_resolved_fingerprints: dict[str, float] = {}


def _persist_state() -> None:
    try:
        now    = time.time()
        active = {fp: ts for fp, ts in _resolved_fingerprints.items() if now - ts < _FINGERPRINT_TTL}
        with open(_STATE_FILE, "w") as f:
            json.dump({"seen_ids": list(_seen_ids), "resolved_fingerprints": active}, f)
    except Exception as e:
        logger.warning("Could not persist consumer state: %s", e)


def _restore_state() -> None:
    try:
        if not os.path.exists(_STATE_FILE):
            return
        with open(_STATE_FILE) as f:
            data = json.load(f)
        now = time.time()
        _seen_ids.update(data.get("seen_ids", []))
        for fp, ts in data.get("resolved_fingerprints", {}).items():
            if now - ts < _FINGERPRINT_TTL:
                _resolved_fingerprints[fp] = ts
        logger.info(
            "Consumer state restored: %d seen IDs, %d active fingerprints",
            len(_seen_ids), len(_resolved_fingerprints),
        )
    except Exception as e:
        logger.warning("Could not restore consumer state: %s", e)


_K8S_POD_SUFFIX = re.compile(r'-[a-z0-9]{8,10}-[a-z0-9]{5}$')


def _deployment_name(service: str) -> str:
    return _K8S_POD_SUFFIX.sub('', service)


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
        logger.warning("Incident %s skipped — [%s] is already being processed", incident_id, fp)
        return

    if fp in _resolved_fingerprints:
        age = now - _resolved_fingerprints[fp]
        if age < _FINGERPRINT_TTL:
            logger.warning(
                "Incident %s skipped — [%s] was resolved %.0fs ago (suppression window: %gs)",
                incident_id, fp, age, _FINGERPRINT_TTL,
            )
            return
        del _resolved_fingerprints[fp]

    _active_fingerprints.add(fp)
    last_error: Exception | None = None

    try:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                t_start     = time.time()
                final_state = run_pipeline(incident)
                elapsed     = time.time() - t_start

                _seen_ids.add(incident_id)
                logger.info("Incident %s processed (attempt %d) in %.1fs", incident_id, attempt, elapsed)

                exec_st   = (final_state or {}).get("execution", {})
                opa_st    = (final_state or {}).get("opa", {})
                comm_st   = (final_state or {}).get("comm", {})
                agent     = comm_st.get("active_agent", "?")
                confirmed = exec_st.get("post_check_confirmed", False)

                print(f"\n{_SEP}")
                if opa_st.get("blocked", False):
                    print(f"  RESULT  →  ✗ OPA BLOCKED   |  Agent: {agent}  |  {elapsed:.1f}s")
                elif exec_st.get("exec_error"):
                    print(f"  RESULT  →  ✗ EXEC FAILED   |  Agent: {agent}  |  {exec_st['exec_error'][:80]}")
                elif confirmed:
                    n_ok = sum(1 for r in (exec_st.get("execution_result") or []) if r.get("status") == "success")
                    plan = exec_st.get("remediation_plan", [])
                    print(f"  RESULT  →  ✓ RESOLVED      |  Agent: {agent}  |  {n_ok}/{len(plan)} actions OK  |  {elapsed:.1f}s")
                else:
                    print(f"  RESULT  →  ✗ UNRESOLVED    |  Agent: {agent}  |  post-check FAILED  |  {elapsed:.1f}s")
                print(f"{_SEP}\n")

                if confirmed and fp not in _resolved_fingerprints:
                    _resolved_fingerprints[fp] = time.time()
                elif not confirmed and fp in _resolved_fingerprints:
                    del _resolved_fingerprints[fp]
                _persist_state()
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
        try:
            from agents.notifier import notify_unresolved
            notify_unresolved(
                incident_id=incident_id,
                service=incident.get("service", ""),
                namespace=incident.get("namespace", ""),
                cause=incident.get("message", "unknown cause"),
                error_detail=f"Pipeline failed after {_MAX_RETRIES} attempts: {last_error}",
            )
        except Exception as notify_exc:
            logger.error("Failed to notify about abandoned incident: %s", notify_exc)
    finally:
        _active_fingerprints.discard(fp)
        _persist_state()


def start_consumer():
    consumer = KafkaConsumer(
        "incidents",
        bootstrap_servers=os.getenv("KAFKA_BROKER"),
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        group_id="agent-llm-group",
        auto_offset_reset="latest"
    )

    _restore_state()
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
