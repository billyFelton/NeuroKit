"""
Convo state: Manage Vox sessions, persist to Vault Postgres.
"""

import os
import uuid
import psycopg2  # Assume in Vault Docker; light for 8GB
from typing import Dict, Any, Optional

def init_session(user_id: str, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Starts Vox chat session; stores init in Vault.

    Generates ID for API tracking.

    Args:
        user_id (str): e.g., 'user123' from FastAPI.
        context (Dict[str, Any], optional): e.g., {'mood': 'neutral'}.

    Returns:
        str: Session UUID.

    Examples:
        >>> from neurokit.convo import init_session
        >>> sid = init_session('user123')

    Raises:
        ConnectionError: Vault DB down.

    Notes:
        - Docker: VAULT_DB_URL=postgresql://...@10.1.1.30:5432.
        - Scalable: Any node routes via Conductor Consul.
        - History: Builds via update_context.
    """
    if context is None:
        context = {}
    db_url = os.getenv('VAULT_DB_URL')
    if not db_url:
        raise ValueError("Set VAULT_DB_URL env.")
    session_id = str(uuid.uuid4())
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
    return session_id

def update_context(session_id: str, new_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merges/updates session; appends to Vault history.

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
        ConnectionError: DB issue.

    Notes:
        - Cadre tie: Use context for ML inference (e.g., sentiment feats).
        - 64GB limit: Prune old sessions if fullness >80% (via health_report).
    """
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
