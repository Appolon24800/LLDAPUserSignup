# --- build stage: collect wheels into /install ---------------------------------
FROM python:3.14-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- runtime: minimal, non-root --------------------------------------------------
FROM python:3.14-slim
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY gunicorn.conf.py .
RUN mkdir -p /data && chown appuser:appuser /data
USER appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/codes.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:create_app()"]
