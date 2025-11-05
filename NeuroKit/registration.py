import pika
import json
import logging
from .utils import get_host_ip, load_state

logger = logging.getLogger(__name__)

def register(
    service,
    port,
    rabbitmq_host="rabbitmq",
    rabbitmq_user="conductor_user",
    rabbitmq_pass="conductor_pass",
):
    state = load_state(service)
    payload = {
        "service": service,
        "host": get_host_ip(),
        "port": port,
        "load": 0,
        "version": "1.0.0",
        "status": state["status"],
        "uid": state["uid"]
    }

    credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_pass)
    parameters = pika.ConnectionParameters(host=rabbitmq_host, credentials=credentials)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.queue_declare(queue="service_registry_queue", durable=True)
    channel.basic_publish(
        exchange="",
        routing_key="service_registry_queue",
        body=json.dumps(payload).encode(),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    connection.close()
    logger.info(f"Sent registration: {payload}")
    return state
