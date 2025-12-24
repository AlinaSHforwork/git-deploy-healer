from prometheus_client import Counter, Gauge

DEPLOYMENT_COUNTER = Counter(
    'pypaas_deployments_total', 
    'Total number of deployment webhooks received'
)

HEALER_RESTART_COUNTER = Counter(
    'pypaas_healer_restarts_total', 
    'Total number of containers restarted by the self-healing daemon'
)

ACTIVE_CONTAINERS_GAUGE = Gauge(
    'pypaas_active_containers', 
    'Number of currently running application containers'
)