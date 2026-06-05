import requests
import json

WEBHOOK_URL = "http://localhost:8000/alert"

SCENARIOS = {

    # ── SIMPLE CASES ──────────────────────────────────────
    "1": {
        "name":      "Platform only — api-gateway CrashLoopBackOff",
        "alertname": "PodCrashLoopBackOff",
        "service":   "api-gateway",
        "namespace": "production",
        "message":   "Pod api-gateway in CrashLoopBackOff restartCount=12 CPU=95% — K8s issue only",
        "source":    "alertmanager"
    },
    "2": {
        "name":      "Integration only — DB connection exhausted",
        "alertname": "DatabaseConnectionExhausted",
        "service":   "postgres-prod",
        "namespace": "production",
        "message":   "DB connection pool saturated 500/500 response_time=8500ms — DB issue only, no K8s",
        "source":    "alertmanager"
    },

    # ── SHARED STATE ──────────────────────────────────────
    "3": {
        "name":      "Shared state: Integration needs K8s data from Platform",
        "alertname": "JenkinsPipelineFailed",
        "service":   "deploy-prod",
        "namespace": "ci-cd",
        "message":   "Jenkins pipeline deploy-prod FAILED build=142 DB timeout — K8s pods api-gateway in CrashLoopBackOff blocking deployment — Integration needs K8s state to correlate",
        "source":    "alertmanager"
    },
    "4": {
        "name":      "Shared state: Platform needs DB data from Integration",
        "alertname": "PodOOMKilledDBLeak",
        "service":   "backend-api",
        "namespace": "production",
        "message":   "Pod backend-api OOMKilled — memory leak caused by unreleased DB connections postgres-prod — Platform needs DB state to correlate",
        "source":    "alertmanager"
    },

    # ── OPA SCENARIOS ─────────────────────────────────────
    "5": {
        "name":      "OPA — Direct approval on first attempt",
        "alertname": "PodCrashLoopBackOff",
        "service":   "frontend",
        "namespace": "production",
        "message":   "Pod frontend CrashLoopBackOff simple restart required — basic K8s action",
        "source":    "alertmanager"
    },
    "6": {
        "name":      "OPA — First plan rejected then second approved",
        "alertname": "JenkinsPipelineFailed",
        "service":   "staging-deploy",
        "namespace": "staging",
        "message":   "Pipeline staging-deploy FAILED — LLM will propose an advanced action rejected by OPA then self-correct with an authorized action",
        "source":    "alertmanager"
    },
    "7": {
        "name":      "OPA — Definitive block after two consecutive rejections",
        "alertname": "DatabaseCriticalFailure",
        "service":   "postgres-prod",
        "namespace": "production",
        "message":   "Database critical failure — corruption detected — LLM will propose unauthorized actions drop_table or modify_credentials causing definitive OPA block",
        "source":    "alertmanager"
    },
}

def send_alert(scenario: dict):
    payload = {
        "alertname": scenario["alertname"],
        "service":   scenario["service"],
        "namespace": scenario["namespace"],
        "message":   scenario["message"],
        "source":    scenario["source"]
    }
    print(f"\nSending alert: {scenario['name']}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(WEBHOOK_URL, json=payload)
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("  TEST SCENARIOS — Multi-Agent System")
    print("=" * 60)
    print("\nSimple cases:")
    for k in ["1", "2"]:
        print(f"  {k} — {SCENARIOS[k]['name']}")
    print("\nShared State:")
    for k in ["3", "4"]:
        print(f"  {k} — {SCENARIOS[k]['name']}")
    print("\nOPA:")
    for k in ["5", "6", "7"]:
        print(f"  {k} — {SCENARIOS[k]['name']}")
    print()
    choice = input("Select scenario (1-7): ")
    if choice in SCENARIOS:
        send_alert(SCENARIOS[choice])
    else:
        print("Invalid scenario")
