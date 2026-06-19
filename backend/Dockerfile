FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/app/data/home
ENV XDG_CACHE_HOME=/app/data/model-cache
ENV HF_HOME=/app/data/model-cache/huggingface
ENV TORCH_HOME=/app/data/model-cache/torch
ENV MPLCONFIGDIR=/app/data/model-cache/matplotlib

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential ca-certificates libglib2.0-0 libgl1 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000
