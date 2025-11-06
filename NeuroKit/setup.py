from setuptools import setup, find_packages
import os

setup(
    name='neurokit',
    version='0.1.3',  # Trimmed deps for clean installs
    packages=find_packages(),
    install_requires=[
        'numpy>=1.24.0',   # Arrays/FFT for signals.py (EEG/ECG sim + feats)
        'scipy>=1.10.0',   # Filtering/normalization in preprocess_signals (low-RAM bands)
        'pika>=1.3.0',     # RabbitMQ payloads in core.py (stateless rego)
        'psutil>=5.9.0'    # CPU/RAM/disk snapshots for health_report (Prometheus hooks)
    ],
    author='Billy Felton',
    description='NeuroKit: Lean lib for NeuroNetwork—signals/orch/convo/health on Ubuntu Docker nodes (4-core/8GB).',
    long_description=open('README.md').read() if os.path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    classifiers=[
        'Programming Language :: Python :: 3.12',
        'License :: OSI Approved :: MIT',
        'Operating System :: POSIX :: Linux (Ubuntu 24.04)',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
    ],
)
