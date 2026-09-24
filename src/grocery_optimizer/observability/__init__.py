"""Logs, metrics and traces for the API.

- log.py      JSON log lines with a per-request ID (and the trace ID when tracing is on)
- metrics.py  Prometheus counters/histograms, served at GET /metrics
- tracing.py  OpenTelemetry spans, printed to the console or sent to an OTLP collector
"""
