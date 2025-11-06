"""
Helpers: Vault logging, node config fetch.
Optional Postgres: Mocks for non-Vault (e.g., Conductor/Cadre).
"""

import os
import psutil
from typing import Any, Dict

# Optional Postgres: Only import if env set (Vault-only dep)
try:
    if os.getenv('VAULT_DB_URL'):
        import psycopg2
        _DB_AVAILABLE = True
    else:
        _DB_AVAILABLE = False
except ImportError:
    _DB_AVAILABLE = False

_log_store = []  # In-memory fallback for non-DB (stateless, per-process)

def log_to_vault(table: str, data: Dict[str, Any]) -> bool:
    """
    Logs dict to Vault Postgres if available, else mocks (stdout/file).

    Args:
        table (str): e.g., 'features' or 'convo_history'.
        data (Dict[str, Any]): Payload.

    Returns:
        bool: Success.

    Examples:
        >>> from neurokit.utils import log_to_vault
        >>> log_to_vault('signals', {'alpha': 0.5})

    Raises:
        ConnectionError: DB configured but fails.

    Notes:
        - VAULT_DB_URL triggers Postgres (Vault node only).
        - Fullness check: Auto-alert if >80% of 64GB via psutil.disk.
        - Mock: Stdout in Conductor; ties to health_report for Cadre feats.
    """
    if _DB_AVAILABLE:
        db_url = os.getenv('VAULT_DB_URL')
        if not db_url:
            raise ValueError("VAULT_DB_URL unset for DB mode.")
        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            columns = ', '.join(data.keys())
            placeholders = ', '.join(['%s'] * len(data))
            cur.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(data.values()))
            conn.commit()
            cur.close()
            conn.close()
            # Fullness alert
            free_gb = psutil.disk_usage('/').free / (1024**3)
            if free_gb < 10:  # 64GB threshold
                print("ALERT: Vault storage low!")
            return True
        except psycopg2.Error as e:
            raise ConnectionError(f"Log fail: {e}")
    else:
        # Mock: Stdout + in-memory for non-Vault (lightweight)
        log_entry = {'table': table, 'data': data, 'timestamp': 'mock_now'}
        _log_store.append(log_entry)
        print(f"Mock Log to {table}: {data}")  # Or write to /tmp/neurokit.log
        free_gb = psutil.disk_usage('/').free / (1024**3)
        if free_gb < 10:
            print("ALERT: Local storage low!")
        return True

def get_node_config(node_id: str) -> Dict[str, str]:
    """
    Fetches config (RAM/CPU) for node; from env or psutil.

    Args:
        node_id (str): e.g., 'node-10.1.1.10'.

    Returns:
        Dict[str, str]: {'ram_gb': '8', 'cpu_cores': '4'}.

    Examples:
        >>> from neurokit.utils import get_node_config
        >>> conf = get_node_config('node-10.1.1.40')  # Cadre

    Notes:
        - Hardcoded for your setup; extend for cloud.
        - Use in register_service for resource-aware orch.
    """
    return {
        'ram_gb': os.getenv('NODE_RAM_GB', '8'),
        'cpu_cores': os.getenv('NODE_CPU_CORES', '4'),
        'storage_gb': '64',
        'os': 'Ubuntu 24.04'
    }
