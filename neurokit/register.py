# neurokit/register.py — THE ONLY REGISTRATION CODE YOU WILL EVER NEED
import os
import json
import uuid
import time
import logging
import pika
from .utils import validate_neuro_env

logger = logging.getLogger(__name__)

def register_service(service_name: str, port: int, custom_data: dict = None) -> str:
    """
    Register this service with Conductor using NeuroKit's shared logic.
    Returns the assigned UID.
    """
    config = validate_neuro_env()
    host_ip = config["HOST_IP"]  # ← This is now 10.10.50.73 (correct)

    payload = {
        "service": service_name,
        "uid": None,
        "host": host_ip,
        "port": port,
        "load": 0,
        "status": "New",
        "version": "1.0.0",
        "timestamp": time.time(),
    }
    if custom_data:
        payload.update(custom_data)

    credentials = pika.PlainCredentials(
        os.getenv("RABBITMQ_USER", "guest"),
        os.getenv("RABBITMQ_PASS", "guest")
    )
    params = pika.ConnectionParameters(
        host=config["CONDUCTOR_HOST"],
        port=5672,
        credentials=credentials
    )

    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue="service_registry_queue", durable=True)

    # Create exclusive reply queue for UID
    reply_queue = channel.queue_declare(queue='', exclusive=True).method.queue
    corr_id = str(uuid.uuid4())

    channel.basic_publish(
        exchange='',
        routing_key="service_registry_queue",
        body=json.dumps(payload),
        properties=pika.BasicProperties(
            reply_to=reply_queue,
            correlation_id=corr_id,
            content_type="application/json",
        )
    )

    logger.info(f"Sent registration for {service_name} at {host_ip}:{port}")

    # Wait for UID reply from Conductor
    uid = None
    for method, properties, body in channel.consume(reply_queue, inactivity_timeout=30):
        if properties.correlation_id == corr_id:
            response = json.loads(body)
            uid = response["uid"]
            logger.info(f"Registration successful — UID: {uid}")
            channel.basic_ack(method.delivery_tag)
            break
        channel.basic_ack(method.delivery_tag)

    connection.close()

    if not uid:
        raise RuntimeError("No UID received from Conductor — registration failed")

    return uid
