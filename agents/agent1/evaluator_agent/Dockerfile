# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tini \
        build-essential \
        libexpat1 \
        libgomp1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libfontconfig1 \
        libice6 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY ./agents/agent1/evaluator_agent /app
COPY ./storage /app/storage

RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    pymongo==4.8.0 \
    psycopg2-binary==2.9.9 \
    pydantic==2.8.2 \
    requests==2.32.3 \
    plotly==5.22.0 \
    kaleido==0.2.1 \
    sqlalchemy>=2.0.0

EXPOSE 8001
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "evaluator_api:app", "--host", "0.0.0.0", "--port", "8001"]
