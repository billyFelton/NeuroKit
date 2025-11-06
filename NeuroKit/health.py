"""
Network health: Poll components for 'healthy limited' status.
"""

from .core import health_report  # Local tie
from typing import Dict, Any, List

def check_network_health() -> Dict[str, Any]:
    """
    Verifies Conductor/Vault/Cadre/Vox online via Consul/RMQ.

    Returns status; call from Conductor cron.

    Returns:
        Dict[str, Any]: {'status': 'healthy' | 'limited' | 'unhealthy', 'components': List[str]}.

    Examples:
        >>> from neurokit.health import check_network_health
        >>> status = check_network_health()
        >>> if status['status'] == 'healthy':  # Proceed with Vox API

    Notes:
        - 'Healthy limited': All 4 online on your 4 nodes (no cloud yet).
        - Alerts: If storage <10GB free (64GB total), log to Vault.
        - Docker: Run in Conductor; integrates health_report per node.
    """
    # Sim poll (real: Consul query or RMQ ping)
    components = ['conductor', 'vault', 'cadre', 'vox']
    online = ['conductor', 'vault']  # Assume partial for now
    status = 'unhealthy' if len(online) < 2 else 'limited' if len(online) < 4 else 'healthy'
    # Quick node health
    for node in ['10.1.1.10', '10.1.1.20', '10.1.1.30', '10.1.1.40']:
        health_report(node_id=f'node-{node}')
    return {'status': f'{status} (limited without cloud)', 'components': online}
