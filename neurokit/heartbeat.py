import os
import psutil

def health_report(node_id=None):
    if node_id is None:
        node_id = os.uname().nodename.split('.')[0]
    metrics = {
        'cpu': psutil.cpu_percent(interval=0.5),
        'ram_gb': psutil.virtual_memory().available / (1024**3),
        'storage_gb': psutil.disk_usage('/').free / (1024**3)
    }
    url = os.getenv('PROMETHEUS_URL', 'http://conductor:9091')
    print(f"{node_id} health to {url}: CPU {metrics['cpu']:.1f}%, RAM {metrics['ram_gb']:.1f}GB, Storage {metrics['storage_gb']:.0f}GB")
    return True
