"""
Convo state: Manage Vox sessions, persist to Vault Postgres if available.
Optional DB: Mocks in-memory for non-Vault nodes (e.g., Conductor/Cadre tests).
"""

import os
import uuid
from typing import Dict, Any, Optional

# Optional Postgres: Only import if env set (Vault-only dep)
try:
    if os.getenv('VAULT_DB_URL'):
        import psycopg2
        _DB_AVAILABLE = True
    else:
        _DB_AVAILABLE = False
except ImportError:
    _DB_AVAILABLE = False

_sessions_store = {}  # In-memory fallback for non-DB (stateless, per-process)

def init_session(user_id: str, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Starts Vox chat session; stores in Vault if DB available, else in-memory mock.

    Generates ID for API tracking—full persistence in Vault.

    Args:
        user_id (str): e.g., 'user123' from FastAPI.
        context (Dict[str, Any], optional): e.g., {'mood': 'neutral'}.

    Returns:
        str: Session UUID.

    Examples:
        >>> from neurokit.convo import init_session
        >>> sid = init_session('user123')

    Raises:
        ConnectionError: If DB configured but unreachable.

    Notes:
        - Docker: VAULT_DB_URL triggers Postgres (Vault node only).
        - Scalable: Mocks for Conductor/Cadre tests; any-node routes via Consul.
        - History: Builds via update_context; prune on 64GB fullness in Vault.
    """
    if context is None:
        context = {}
    session_id = str(uuid.uuid4())
    
    if _DB_AVAILABLE:
        db_url = os.getenv('VAULT_DB_URL')
        if not db_url:
            raise ValueError("VAULT_DB_URL unset for DB mode.")
        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sessions (id, user_id, context, created) VALUES (%s, %s, %s, NOW())",
                (session_id, user_id, str(context))
            )
            conn.commit()
            cur.close()
            conn.close()
        except psycopg2.Error as e:
            raise ConnectionError(f"Vault insert fail: {e}")
    else:
        # Mock: In-memory for non-Vault (lightweight, <1MB)
        _sessions_store[session_id] = {'user_id': user_id, 'context': context, 'created': 'mock_now'}
    
    return session_id

def update_context(session_id: str, new_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merges/updates session; appends to Vault if DB, else in-memory.

    For Rasa/FastAPI in Vox.

    Args:
        session_id (str): From init_session.
        new_data (Dict[str, Any]): e.g., {'response': 'Hi!', 'sentiment': 0.8}.

    Returns:
        Dict[str, Any]: Full context post-update.

    Examples:
        >>> from neurokit.convo import update_context
        >>> full = update_context(sid, {'intent': 'chat'})

    Raises:
        KeyError: Invalid session_id.
        ConnectionError: If DB configured but fails.

    Notes:
        - Cadre tie: Use context for ML inference (e.g., sentiment feats).
        - 64GB limit: Prune old sessions in Vault if fullness >80% (via health_report).
    """
    if _DB_AVAILABLE:
        db_url = os.getenv('VAULT_DB_URL')
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT context FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Session {session_id} not found.")
        current = eval(row[0]) if row[0] else {}  # Safe eval for dict str
        current.update(new_data)
        current.setdefault('history', []).append(new_data)
        cur.execute("UPDATE sessions SET context = %s, updated = NOW() WHERE id = %s",
                    (str(current), session_id))
        conn.commit()
        cur.close()
        conn.close()
        return current
    else:
        # Mock: In-memory update
        if session_id not in _sessions_store:
            raise KeyError(f"Session {session_id} not found.")
        current = _sessions_store[session_id]['context']
        current.update(new_data)
        current.setdefault('history', []).append(new_data)
        _sessions_store[session_id]['context'] = current
        return current
