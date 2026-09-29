# syntax=docker/dockerfile:1
# Aviation Intelligence RAG — FastAPI backend (CPU only, ~0.4 GB RAM at runtime)

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# ---- build: dependencies + pre-downloaded embedding model --------------------------------
FROM base AS builder
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install -r requirements.txt
# Bake the model into the image so containers start without downloading it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}', cache_dir='/models')"

# ---- runtime ---------------------------------------------------------------------------------
FROM base AS runtime
RUN useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=app:app /models /models
ENV PATH=/opt/venv/bin:$PATH \
    EMBEDDING_CACHE_DIR=/models \
    HF_HUB_OFFLINE=1 \
    ENVIRONMENT=production
COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations
USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status == 200 else 1)"

# One worker on purpose: each worker would load its own copy of the embedding model.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
