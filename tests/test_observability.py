"""Structured logging, Prometheus metrics and OpenTelemetry tracing."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY

from grocery_optimizer.api import create_app
from grocery_optimizer.config import SYNTHETIC_IMAGES_DIR
from grocery_optimizer.extraction import DemoReceiptExtractor
from grocery_optimizer.observability.log import JsonFormatter, request_id_var
from grocery_optimizer.observability.tracing import exporter_name


class ListHandler(logging.Handler):
    """Collects formatted JSON log lines so tests can inspect them."""

    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[dict] = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def logs():
    handler = ListHandler()
    logger = logging.getLogger("grocery_optimizer.api")
    logger.addHandler(handler)
    yield handler.lines
    logger.removeHandler(handler)


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", extractor=DemoReceiptExtractor())
    with TestClient(app) as c:
        yield c


def _metric(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ----- logging -------------------------------------------------------------------
def test_json_formatter_includes_extras_and_request_id():
    record = logging.makeLogRecord({"name": "x", "levelname": "INFO", "msg": "hello %s",
                                    "args": ("world",), "store": "Aldi"})
    token = request_id_var.set("abc123")
    try:
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["message"] == "hello world" and line["store"] == "Aldi"
    assert line["request_id"] == "abc123" and line["level"] == "INFO"
    assert "trace_id" not in line  # no active span


def test_request_id_is_generated_echoed_and_logged(client, logs):
    r = client.get("/api/health")
    generated = r.headers["X-Request-ID"]
    assert len(generated) == 32
    r = client.get("/api/stores", headers={"X-Request-ID": "from-the-caller"})
    assert r.headers["X-Request-ID"] == "from-the-caller"
    access = [line for line in logs if line["message"] == "request"]
    assert access[-1]["request_id"] == "from-the-caller"
    assert access[-1]["route"] == "/api/stores" and access[-1]["status"] == 200
    assert access[0]["request_id"] == generated


def test_request_id_reaches_logs_written_inside_endpoints(client, logs):
    # The plan endpoint is sync, so FastAPI runs it in a worker thread.
    client.post("/api/demo/load", json={"reset": True})
    items = client.get("/api/demo/shopping-list").json()
    client.post("/api/plan", json={"items": items}, headers={"X-Request-ID": "plan-req"})
    [plan_line] = [line for line in logs if line["message"] == "plan computed"]
    assert plan_line["request_id"] == "plan-req" and plan_line["status"] == "Optimal"


# ----- metrics -------------------------------------------------------------------
def test_metrics_endpoint_counts_requests_by_route_template(client):
    labels = {"method": "GET", "route": "/api/receipts/{receipt_id}/items", "status": "200"}
    before = _metric("http_requests_total", **labels)
    client.get("/api/receipts/1/items")
    client.get("/api/receipts/2/items")
    assert _metric("http_requests_total", **labels) == before + 2
    body = client.get("/metrics")
    assert body.status_code == 200 and body.headers["content-type"].startswith("text/plain")
    assert "http_request_duration_seconds_bucket" in body.text


def test_domain_metrics(client):
    ok_before = _metric("receipts_extracted_total", extractor="demo", outcome="success")
    err_before = _metric("receipts_extracted_total", extractor="demo", outcome="error")
    solves_before = _metric("optimizer_solve_seconds_count")

    image = next(SYNTHETIC_IMAGES_DIR.glob("SYNTHETIC_aldi_*.png"))
    client.post("/api/receipts/extract", files={"file": (image.name, image.read_bytes(), "image/png")})
    client.post("/api/receipts/extract", files={"file": ("unknown.png", b"x", "image/png")})
    client.post("/api/demo/load", json={"reset": True})
    client.post("/api/plan", json={"items": [{"product": "banana", "quantity": 1}]})

    assert _metric("receipts_extracted_total", extractor="demo", outcome="success") == ok_before + 1
    assert _metric("receipts_extracted_total", extractor="demo", outcome="error") == err_before + 1
    assert _metric("optimizer_solve_seconds_count") == solves_before + 1
    assert _metric("line_items_matched_total", method="fuzzy") > 0


# ----- tracing -------------------------------------------------------------------
def test_tracing_is_off_in_tests(client):
    assert client.app.state.tracing is False


def test_exporter_choice_from_environment(monkeypatch):
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert exporter_name() == "console"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert exporter_name() == "otlp"
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    assert exporter_name() == "none"


def test_spans_for_extraction_matching_and_optimization(tmp_path, logs):
    exporter = InMemorySpanExporter()
    app = create_app(db_path=tmp_path / "t.db", extractor=DemoReceiptExtractor(),
                     span_exporter=exporter)
    with TestClient(app) as c:
        image = next(SYNTHETIC_IMAGES_DIR.glob("SYNTHETIC_aldi_*.png"))
        c.post("/api/receipts/extract", files={"file": (image.name, image.read_bytes(), "image/png")})
        c.post("/api/demo/load", json={"reset": True})
        c.post("/api/plan", json={"items": [{"product": "banana", "quantity": 1}], "trip_cost": 2})
        c.get("/healthz")  # excluded from tracing

    spans = {s.name: s for s in exporter.get_finished_spans()}
    extract, match, plan = spans["receipt.extract"], spans["receipt.match"], spans["plan.optimize"]
    assert extract.attributes["extractor"] == "demo"
    assert match.attributes["receipt.line_items"] == extract.attributes["receipt.line_items"]
    assert plan.attributes["plan.status"] == "Optimal"
    # Our spans are children of the HTTP request span that FastAPIInstrumentor creates.
    request_span = spans["POST /api/receipts/extract"]
    assert extract.context.trace_id == request_span.context.trace_id
    assert extract.parent.span_id == request_span.context.span_id
    assert not any("healthz" in name for name in spans)
    # Log lines written during a traced request carry its trace ID.
    [plan_log] = [line for line in logs if line["message"] == "plan computed"]
    assert plan_log["trace_id"] == format(plan.context.trace_id, "032x")
