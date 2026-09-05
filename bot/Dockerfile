# --- build stage ------------------------------------------------------------------
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- runtime: non-root, no exposed ports (long polling only) ------------------------
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY bot ./bot
USER appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
CMD ["python", "-m", "bot.main"]
