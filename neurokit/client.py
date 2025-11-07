| `/neurokit/client.py` | RabbitMQ RPC register; state check; persistence | ```python
import os
import uuid
import json
import pika
import logging
from .models import RegisterPayload, RegisterStatus
from pathlib import Path

DATA_DIR = Path(os.getenv("NEUROKIT_DATA_DIR", "/data/neurokit"))
UID_FILE = DATA_DIR / "uid.txt"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _get_rabbitmq_creds():
    return pika.PlainCredentials(
        os.getenv("RABBITMQ_USER", "guest"),
        os.getenv("RABBITMQ_PASS", "guest")
    )

def register_with_conductor(service: str, port: int, host: str = None):
    host = host or os.getenv("HOST_IP") or socket.gethostbyname(socket.gethostname())
    uid = None
    status = RegisterStatus.FAULT

    if UID_FILE.exists():
        try:
            uid = UID_FILE.read_text().strip()
            status = RegisterStatus.REBOOTING
            logging.info(f"Rebooting with persisted UID: {uid}")
        except Exception as e:
            logging.error(f"UID read fail: {e}")
    else:
        status = RegisterStatus.NEW
        logging.info("New instance - requesting UID")

    payload = RegisterPayload(
        service=service,
        uid=uid,
        host=host,
        port=port,
        status=status
    ).json()

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=os.getenv("CONDUCTOR_HOST", "10.1.1.20"),
            credentials=_get_rabbitmq_creds()
        )
    )
    channel = connection.channel()
    channel.queue_declare(queue="service_registry_queue", durable=True)

    corr_id = str(uuid.uuid4())
    reply_queue = channel.queue_declare(queue='', exclusive=True).method.queue

    channel.basic_publish(
        exchange='',
        routing_key="service_registry_queue",
        properties=pika.BasicProperties(
            reply_to=reply_queue,
            correlation_id=corr_id
        ),
        body=payload
    )

    response = None
    for method, props, body in channel.consume(reply_queue, inactivity_timeout=30):
        if props.correlation_id == corr_id:
            response = json.loads(body)
            channel.cancel()
            break

    if not response or "uid" not in response:
        raise RuntimeError("Registration failed - no UID from Conductor")

    assigned_uid = response["uid"]
    UID_FILE.write_text(assigned_uid)
    os.chmod(UID_FILE, 0o600)
    logging.info(f"Registered with UID: {assigned_uid}")
    connection.close()
    return assigned_uid
``` |
| `/neurokit/heartbeat.py` (new) | Periodic updates (stub for now) | Reuse queue; non-RPC publish with updated load/status="passing". Cron in entrypoint. |
| `pyproject.toml` / `requirements.txt` | Add pika | `pika==1.3.2` |

#### Component Integration Example (e.g., Vox entrypoint.sh → Python)
```python
from neurokit.client import register_with_conductor
import os

uid = register_with_conductor(
    service="vox",
    port=int(os.getenv("VOX_PORT", 8000))
)
# Proceed to start FastAPI/Rasa
# Thread: every 30s heartbeat(uid, current_load())
