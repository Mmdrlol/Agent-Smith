FROM python:3.10-slim

RUN apt-get update && \
        apt-get install -y git && \
        rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install "mcp[cli]" pydantic pytest

WORKDIR /testbed
