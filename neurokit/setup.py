from setuptools import setup, find_packages

setup(
    name='neurokit',
    version='0.2.1',
    packages=find_packages(),
    install_requires=[
        'pika>=1.3.0',
        'psutil>=5.9.0',
        'flask>=3.0.0',
        'python-consul>=1.1.0'
    ],
)
