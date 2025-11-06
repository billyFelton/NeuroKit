import os
import time
import pika

def register_service(service_name, endpoint, node_id, retries=3):
    rmq_url = os.getenv('CONDUCTOR_RMQ_URL', 'amqp://guest:guest@conductor:5672')
    for attempt in range(retries):
        try:
            conn = pika.BlockingConnection(pika.URLParameters(rmq_url))
            ch = conn.channel()
            ch.queue_declare(queue='service_registrations', durable=True)
            payload = {
                'service': service_name,
                'endpoint': endpoint,
                'node_id': node_id,
                'timestamp': time.time()
            }
            ch.basic_publish(exchange='', routing_key='service_registrations',
                             body=str(payload), properties=pika.BasicProperties(delivery_mode=2))
            conn.close()
            return {'status': 'registered', 'token': f'token_{service_name}_{node_id}',
                    'consul_key': f'services/{service_name}'}
        except pika.exceptions.AMQPConnectionError:
            if attempt == retries - 1:
                raise ConnectionError(f"RMQ fail after {retries} tries")
            time.sleep(2 ** attempt)
