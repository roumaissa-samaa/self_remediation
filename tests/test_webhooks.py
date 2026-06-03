import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

from agents.notifier import notify_teams_resolved, notify_teams_critical, _post_teams
from orchestrator.state import AgentState, IncidentInfo, ObservabilityData, PlatformState, IntegrationState, CommunicationState, OPAState, ExecutionState
from agents.notifier import notify_operator
from datetime import datetime, timezone

FAKE_INCIDENT = {
    "incident_id": "test-webhook-001",
    "alertname":   "PodCrashLoopBackOff",
    "service":     "api-gateway-prod",
    "namespace":   "production",
}

def test_resolved():
    print("\n[1/3] Test RESOLVED → channel resolved")
    notify_teams_resolved(
        incident_id=FAKE_INCIDENT["incident_id"],
        alertname=FAKE_INCIDENT["alertname"],
        service=FAKE_INCIDENT["service"],
        namespace=FAKE_INCIDENT["namespace"],
        agent="platform",
        n_ok=3,
        n_total=3,
    )
    print("     Notification envoyée (vérifier channel 'resolved')")

def test_critical_postcheck():
    print("\n[2/3] Test CRITICAL (post-check failed) → channel critical")
    notify_teams_critical(
        incident_id=FAKE_INCIDENT["incident_id"],
        alertname=FAKE_INCIDENT["alertname"],
        service=FAKE_INCIDENT["service"],
        namespace=FAKE_INCIDENT["namespace"],
        agent="platform",
        n_ok=1,
        n_total=3,
        reason="post-check FAILED — deployment not healthy",
    )
    print("     Notification envoyée (vérifier channel 'critical')")

def test_critical_opa_block():
    print("\n[3/3] Test CRITICAL (OPA block) → channel critical")
    fake_state = AgentState(
        incident=IncidentInfo(
            incident_id=FAKE_INCIDENT["incident_id"],
            alertname=FAKE_INCIDENT["alertname"],
            service=FAKE_INCIDENT["service"],
            namespace=FAKE_INCIDENT["namespace"],
            message="test OPA block",
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        obs=ObservabilityData(
            logs=[], metrics={}, infra_state={},
            incident_type="platform",
            incident_cause="CrashLoopBackOff détecté",
            root_cause_hypothesis="",
            affected_components=[],
            classification={},
        ),
        platform=PlatformState(k8s_state={}, config={}),
        integration=IntegrationState(config={}, jenkins_state={}, db_state={}),
        comm=CommunicationState(
            active_agent="platform",
            needs_more_data=False,
            extra_request="",
            extra_data={},
            requesting_agent="",
            responding_agent="",
            just_responded="",
        ),
        opa=OPAState(
            approved=False,
            reason="Action drop_table non autorisée en production",
            retry_count=2,
        ),
        execution=ExecutionState(
            remediation_plan=[{"action": "drop_table", "target": "users"}],
            execution_result={},
            audit_trail=[],
            resolved=False,
        ),
    )
    notify_operator(fake_state)
    print("     Notification envoyée (vérifier channel 'critical')")

TESTS = {
    "1": ("RESOLVED — post-check OK",           test_resolved),
    "2": ("CRITICAL — post-check FAILED",        test_critical_postcheck),
    "3": ("CRITICAL — OPA bloqué (max retries)", test_critical_opa_block),
    "4": ("Tous les tests",                      None),
}

if __name__ == "__main__":
    print("=" * 58)
    print("  TEST WEBHOOKS TEAMS")
    print("=" * 58)
    for k, (label, _) in TESTS.items():
        print(f"  {k} — {label}")
    print()
    choice = input("Choisir test (1-4) : ").strip()

    if choice == "4":
        test_resolved()
        test_critical_postcheck()
        test_critical_opa_block()
    elif choice in TESTS and TESTS[choice][1]:
        TESTS[choice][1]()
    else:
        print("Choix invalide")
