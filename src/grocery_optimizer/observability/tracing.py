"""OpenTelemetry tracing.

A *trace* is one request's journey; it is made of *spans* (timed steps such
as "receipt.extract" or "optimizer.solve"). FastAPIInstrumentor creates a
span per HTTP request, and our code adds child spans for the interesting
steps, so a slow request shows exactly which step was slow.

Where spans go (standard OpenTelemetry environment variables):
- OTEL_TRACES_EXPORTER=none      tracing off (the tests use this)
- OTEL_EXPORTER_OTLP_ENDPOINT    send to a collector / Jaeger / Tempo over OTLP HTTP,
                                 e.g. http://localhost:4318
- otherwise                      print finished spans to the console
- OTEL_SERVICE_NAME              service name on every span (default grocery-optimizer)

Code that creates spans only depends on the lightweight `opentelemetry-api`;
without a configured provider those calls are no-ops.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

_provider: TracerProvider | None = None


def exporter_name() -> str:
    """'none', 'otlp' or 'console', from the environment."""
    configured = os.environ.get("OTEL_TRACES_EXPORTER", "").strip().lower()
    if configured:
        return configured
    return "otlp" if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") else "console"


def _global_provider() -> TracerProvider:
    # OpenTelemetry allows setting the global provider only once per process.
    global _provider
    if _provider is None:
        service = os.environ.get("OTEL_SERVICE_NAME", "grocery-optimizer")
        _provider = TracerProvider(resource=Resource.create({"service.name": service}))
        trace.set_tracer_provider(_provider)
    return _provider


def setup_tracing(app: FastAPI, exporter: SpanExporter | None = None) -> bool:
    """Instrument `app`. Tests pass an in-memory exporter. Returns True if tracing is on."""
    if exporter is not None:
        processor = SimpleSpanProcessor(exporter)  # export immediately (tests)
    else:
        name = exporter_name()
        if name == "none":
            return False
        if name == "otlp":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter()  # reads OTEL_EXPORTER_OTLP_ENDPOINT itself
        else:
            exporter = ConsoleSpanExporter()
        processor = BatchSpanProcessor(exporter)  # export in a background thread
    provider = _global_provider()
    provider.add_span_processor(processor)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider,
                                       excluded_urls="healthz,readyz,metrics")
    return True
