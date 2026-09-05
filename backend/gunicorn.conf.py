"""Gunicorn configuration: threads over workers-per-core to bound memory."""

bind = "0.0.0.0:8000"
workers = 2
threads = 4
timeout = 60
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
loglevel = "info"
