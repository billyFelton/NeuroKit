from setuptools import setup, find_packages
import os

setup(
    name='neurokit',
    version='0.1.2',  # Bump for dep fix
    packages=find_packages(),
    install_requires=[
        'numpy>=1.24.0',       # For signals.py arrays/FFT (Cadre feats)
        'scipy>=1.10.0',       # For filtering in preprocess_signals
        'pika>=1.3.0',         # RabbitMQ rego in core.py (Conductor joins)
        'psutil>=5.9.0',       # Health metrics (Prometheus pings)
        'psycopg2-binary>=2.9.0'  # Vault Postgres hooks (add for convo history)
    ],
    author='Billy Felton',
    description='NeuroKit: Core lib for NeuroNetwork—signals/orch/convo/health on Ubuntu Docker nodes.',
    long_description=open('README.md').read() if os.path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    classifiers=[
        'Programming Language :: Python :: 3.12',
        'License :: OSI Approved :: MIT',
        'Operating System :: POSIX :: Linux (Ubuntu 24.04)',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
    ],
)
