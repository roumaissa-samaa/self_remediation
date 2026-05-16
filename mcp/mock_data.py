MOCK_DATA = {

    "observability": {
        "logs": [
            "2026-04-20 ERROR api-gateway CrashLoopBackOff restartCount=12 CPU=95%",
            "2026-04-20 ERROR frontend OOMKilled memory=98% limit=512Mi",
            "2026-04-20 ERROR deploy-prod pipeline FAILED build=142 DB_timeout",
            "2026-04-20 ERROR postgres-prod connections=500 max=500 exhausted",
            "2026-04-20 ERROR backend-api OOMKilled DB_connections_not_released"
        ],
        "metrics": {
            "api_gateway_cpu":       95,
            "api_gateway_memory":    88,
            "api_gateway_restarts":  12,
            "frontend_memory":       98,
            "frontend_restarts":     3,
            "backend_api_memory":    99,
            "db_connections":        500,
            "db_max_connections":    500,
            "db_response_time_ms":   8500,
            "build_failure_rate":    100
        }
    },

    "platform": {
        "infra_state": {
            "pods": [
                {
                    "name":      "api-gateway-xxx",
                    "namespace": "production",
                    "status":    "CrashLoopBackOff",
                    "restarts":  12,
                    "cpu":       "95%",
                    "memory":    "88%"
                },
                {
                    "name":      "frontend-xxx",
                    "namespace": "production",
                    "status":    "OOMKilled",
                    "restarts":  3,
                    "cpu":       "40%",
                    "memory":    "98%"
                },
                {
                    "name":      "backend-api-xxx",
                    "namespace": "production",
                    "status":    "OOMKilled",
                    "restarts":  5,
                    "cpu":       "50%",
                    "memory":    "99%",
                    "note":      "DB connections not released causing memory leak"
                }
            ],
            "nodes": [
                {"name": "worker-node-1", "status": "Ready", "cpu": "85%", "memory": "78%"},
                {"name": "worker-node-2", "status": "Ready", "cpu": "60%", "memory": "65%"}
            ]
        },
        "platform_config": {
            "cluster":   "prod-cluster",
            "namespace": "production",
            "deployments": [
                {"name": "api-gateway",  "replicas": 3, "image": "api-gateway:v1.2.3",  "namespace": "production"},
                {"name": "frontend",     "replicas": 2, "image": "frontend:v2.1.0",     "namespace": "production"},
                {"name": "backend-api",  "replicas": 2, "image": "backend-api:v3.0.1",  "namespace": "production"}
            ],
            "available_actions": ["restart_pod", "scale_deployment", "rollback_deployment"]
        }
    },

    "integration": {
        "jenkins_state": {
            "pipelines": [
                {
                    "name":         "deploy-prod",
                    "status":       "FAILED",
                    "build":        142,
                    "error":        "DB connection timeout during deployment",
                    "duration_min": 30,
                    "last_success": "build 141"
                },
                {
                    "name":     "staging-deploy",
                    "status":   "SUCCESS",
                    "build":    88
                }
            ]
        },
        "db_state": {
            "databases": [
                {
                    "host":               "postgres-prod",
                    "connections":        500,
                    "max_connections":    500,
                    "status":             "exhausted",
                    "response_time_ms":   8500,
                    "leaked_connections": 120,
                    "note":               "backend-api not releasing connections"
                },
                {
                    "host":        "postgres-staging",
                    "connections": 45,
                    "status":      "healthy"
                }
            ]
        },
        "integration_config": {
            "jenkins_url":      "http://jenkins:8080",
            "pipelines":        ["deploy-prod", "staging-deploy"],
            "db_host":          "postgres-prod",
            "available_actions": ["retrigger_build", "restart_service",
                                  "clear_cache", "restart_db_connection"]
        }
    }
}