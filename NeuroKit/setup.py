from setuptools import setup, find_packages

setup(
    name='neurokit',
    version='0.1.1',  # Bumped post-merge
    packages=find_packages(),
    install_requires=[
        'numpy>=1.24.0',
        'scipy>=1.10.0',
        'pika>=1.3.0',
        'psutil>=5.9.0'
    ],
    author='Billy Felton',
    description='NeuroKit: Foundation lib for NeuroNetwork (signals, orchestration, convo, health). Optimized for 4-core/8GB Ubuntu Docker nodes.',
    long_description=open('README.md').read() if os.path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    classifiers=[
        'Programming Language :: Python :: 3.12',
        'License :: OSI Approved :: MIT',
        'Operating System :: POSIX :: Linux (Ubuntu 24.04)',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
    ],
)
