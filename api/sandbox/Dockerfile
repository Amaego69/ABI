# Pre-baked sandbox image so containers can run with network_mode=none
# (pip install at runtime would require outbound network).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "pydantic>=2.0.0" \
    "pytest>=8.0.0" \
    "httpx>=0.27.0"

WORKDIR /work
