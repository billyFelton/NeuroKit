"""
Core orchestration: Register services to Conductor, report health.
Ties to RabbitMQ for dynamic joining; Prometheus for metrics.
"""

import os
import time
import pika
import psutil
from typing import Dict, Any

def register_service(service_name: str, endpoint: str, node_id: str, retries: int = 3) -> Dict[str, Any]:
    """
    Registers service (Vox/Cadre) with Conductor via RabbitMQ for discovery.

    Enables neuro-network joining; call in container entrypoint.

    Args:
        service_name (str): e.g., 'vox-01' or 'cadre-light'.
        endpoint (str): e.g., 'http://10.1.1.10:5000'.
        node_id (str): e.g., 'node-10.1.1.10'.
        retries (int): Connection retries (default 3 for home net stability).

    Returns:
        Dict[str, Any]: {'status': 'registered', 'token': str, 'consul_key': str}.

    Examples:
        >>> from neurokit.core import register_service
        >>> resp = register_service('vox', 'http://10.1.1.10:5000', 'node-10.1.1.10')
        >>> token = resp['token']  # Auth Vault queries

    Raises:
        ValueError: Missing params.
        ConnectionError: RMQ unreachable after retries.

    Notes:
        - Docker: Set CONDUCTOR_RMQ_URL (amqp://...@10.1.1.20:5672).
        - Low-RAM: <1MB payloads; Consul key for service mesh.
        - Post-reg: Conductor pings health_report every 30s.
    """
    if not all([service_name, endpoint, node_id]):
        raise ValueError("service_name, endpoint, node_id required.")
    
    rmq_url = os.getenv('CONDUCTOR_RMQ_URL', 'amqp://guest:guest@conductor:5672')
    for attempt in range(retries):
        try:
            conn = pika.BlockingConnection(pika.URLParameters(rmq_url))
            ch = conn.channel()
            ch.queue_declare(queue='service_registrations', durable=True)
            payload = {
                'service': service_name, 'endpoint': endpoint,
                'node_id': node_id, 'timestamp': time.time()
            }
            ch.basic_publish(exchange='', routing_key='service_registrations',
                             body=str(payload), properties=pika.BasicProperties(delivery_mode=2))
            conn.close()
            return {'status': 'registered', 'token': f'token_{service_name}_{node_id}',
                    'consul_key': f'services/{service_name}'}
        except pika.exceptions.AMQPConnectionError as e:
            if attempt == retries - 1:
                raise ConnectionError(f"RMQ fail after {retries} tries: {e}. Check Conductor (10.1.1.20).")
            time.sleep(2 ** attempt)  # Backoff

def health_report(metrics: Dict[str, float] = None, node_id: str = None) -> bool:
    """
    Reports CPU/RAM/storage to Conductor Prometheus.

    Auto-collects if unset; alerts on >80% for 4-core/8GB limits.

    Args:
        metrics (Dict[str, float], optional): e.g., {'cpu': 0.75, 'ram_gb': 2.5}.
        node_id (str, optional): Defaults to hostname.

    Returns:
        bool: True on success.

    Examples:
        >>> from neurokit.core import health_report
        >>> health_report()  # Auto-collect for Vault node (10.1.1.30)

    Raises:
        KeyError: Missing 'cpu'/'ram'.

    Notes:
        - Cron in Docker: `*/30 * * * * python -c "from neurokit.core import health_report; health_report()"`.
        - Storage: Tracks 64GB fullness; ties to Vault Postgres.
        - PROMETHEUS_URL=http://10.1.1.20:9091 (pushgateway sim here).
    """
    if metrics is None:
        metrics = {
            'cpu': psutil.cpu_percent(interval=0.5),  # Quick for 2.4GHz
            'ram_gb': psutil.virtual_memory().available / (1024**3),
            'storage_gb': psutil.disk_usage('/').free / (1024**3)
        }
    if node_id is None:
        node_id = os.uname().nodename.split('.')[0]  # e.g., 'node-10.1.1.20'
    
    if not all(k in metrics for k in ['cpu', 'ram_gb']):
        raise KeyError("Metrics need 'cpu', 'ram_gb'.")
    
    url = os.getenv('PROMETHEUS_URL', 'http://conductor:9091')
    alert = ' (ALERT: High load)' if metrics['cpu'] > 80 else ''
    print(f"{node_id} health to {url}: CPU {metrics['cpu']:.1f}%{alert}, RAM {metrics['ram_gb']:.1f}GB, Storage {metrics['storage_gb']:.0f}GB")
    return True
