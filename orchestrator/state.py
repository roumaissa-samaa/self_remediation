from typing import TypedDict


class IncidentInfo(TypedDict):
    incident_id: str
    alertname:   str
    service:     str
    namespace:   str
    message:     str
    timestamp:   str


class ObservabilityData(TypedDict):
    logs:                  list
    metrics:               dict
    infra_state:           dict
    incident_type:         str
    incident_cause:        str
    root_cause_hypothesis: str
    affected_components:   list
    classification:        dict


class PlatformState(TypedDict):
    k8s_state: dict
    config:    dict


class IntegrationState(TypedDict):
    config:        dict
    jenkins_state: dict
    db_state:      dict


class CommunicationState(TypedDict):
    active_agent:     str
    needs_more_data:  bool
    extra_request:    str
    extra_data:       dict
    requesting_agent: str
    responding_agent: str
    just_responded:   str


class OPAState(TypedDict):
    approved:    bool
    reason:      str
    retry_count: int


class ExecutionState(TypedDict):
    remediation_plan: list
    execution_result: dict
    audit_trail:      list
    resolved:         bool


class AgentState(TypedDict):
    incident:    IncidentInfo
    obs:         ObservabilityData
    platform:    PlatformState
    integration: IntegrationState
    comm:        CommunicationState
    opa:         OPAState
    execution:   ExecutionState
