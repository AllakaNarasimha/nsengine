from setuptools import setup, find_packages

setup(
    name="nslogger",
    version="0.1.0",
    description="SQLite logging library for ticks and orders",
    author="Your Name",
    packages=find_packages(),
    install_requires=[],
    python_requires=">=3.6",
    include_package_data=True,
    package_data={
        "": ["*.py"],
    },
    scripts=["test_tick_consumer.py"],
)