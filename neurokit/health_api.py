from flask import Flask, jsonify
import consul
import psutil
import os

def create_health_app(service_name):
    app = Flask(__name__)
    c = consul.Consul(host='conductor', port=8500)

    @app.route('/health')
    def health():
        metrics = {
            'status': 'healthy',
            'cpu': psutil.cpu_percent(),
            'ram_gb': psutil.virtual_memory().available / (1024**3),
            'service': service_name
        }
        c.agent.service.register(
            name=service_name,
            service_id=f"{service_name}-{os.getenv('NODE_IP', 'local')}",
            address=os.getenv('NODE_IP', '10.1.1.20'),
            port=9090,
            check=consul.Check.http(f"http://{os.getenv('NODE_IP', '10.1.1.20')}:9090/health", interval="10s")
        )
        return jsonify(metrics)

    return app
