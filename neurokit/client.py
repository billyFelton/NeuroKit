import os
import uuid
import json
import pika
import logging
import socket
from pathlib import Path
from .models import RegisterPayload, RegisterStatus
from .utils import validate_neuro_env, NeuroKitEnvError

logging.basicConfig(level=logging.INFO)

DATA_DIR = Path(os.getenv("NEUROKIT_DATA_DIR", "/data/neurokit"))
UID_FILE = DATA_DIR / "uid.txt"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _get_rabbitmq_creds():
    return pika.PlainCredentials(
        os.getenv("RABBITMQ_USER", "guest"),
        os.getenv("RABBITMQ_PASS", "guest")
    )

def register_with_conductor(service: str, port: int, host: str = None):
    try:
        config = validate_neuro_env()
    except NeuroKitEnvError as e:
        logging.critical(str(e))
        raise

    host = host or config["HOST_IP"]
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

    payload_dict = {
        "service": service,
        "uid": uid,
        "host": host,
        "port": port,
        "load": 0,
        "status": status.value
    }
    payload = json.dumps(payload_dict)  # Use json for RPC simplicity

    params = pika.ConnectionParameters(
        host=config["CONDUCTOR_HOST"],
        port=5672,
        credentials=_get_rabbitmq_creds()
    )
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue="service_registry_queue", durable=True)

    corr_id = str(uuid.uuid4())
    result = channel.queue_declare(queue='', exclusive=True)
    reply_queue = result.method.queue

    channel.basic_publish(
        exchange='',
        routing_key="service_registry_queue",
        properties=pika.BasicProperties(
            reply_to=reply_queue,
            correlation_id=corr_id,
            content_type='application/json'
        ),
        body=payload
    )

    # Wait for reply with timeout
    response = None
    timeout = 30  # Seconds
    start_time = time.time()
    while time.time() - start_time < timeout:
        method_frame, header_frame, body = channel.basic_get(reply_queue, auto_ack=False)
        if method_frame:
            if header_frame.correlation_id == corr_id:
                response = json.loads(body)
                channel.basic_ack(method_frame.delivery_tag)
                break
            else:
                channel.basic_nack(method_frame.delivery_tag)
        else:
            time.sleep(0.1)

    connection.close()

    if not response or "uid" not in response:
        raise RuntimeError("Registration failed - no UID from Conductor")

    assigned_uid = response["uid"]
    UID_FILE.write_text(assigned_uid)
    os.chmod(UID_FILE, 0o600)
    logging.info(f"Registered with UID: {assigned_uid}")
    return assigned_uid
