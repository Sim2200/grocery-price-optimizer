"""Prometheus metrics.

Prometheus *pulls*: it calls GET /metrics every few seconds and stores the
numbers. We only keep counters and histograms in memory here.

- Counter:   only goes up (requests served, receipts extracted). Prometheus
             turns it into a rate, e.g. requests per second.
- Histogram: counts observations into buckets (request latency), so
             Prometheus can compute percentiles such as p95 latency.

Labels split a metric into series (e.g. by route). Route labels use the route
*template* (`/api/receipts/{receipt_id}`), not the raw path, so the number of
series stays small.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests served", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))

# ----- domain metrics ---------------------------------------------------------
RECEIPTS_EXTRACTED = Counter(
    "receipts_extracted_total", "Receipt extraction attempts", ["extractor", "outcome"])
RECEIPTS_SAVED = Counter(
    "receipts_saved_total", "Reviewed receipts saved to the price database", ["source"])
LINES_MATCHED = Counter(
    "line_items_matched_total", "Receipt lines by how they were matched to a product", ["method"])
OPTIMIZER_SECONDS = Histogram(
    "optimizer_solve_seconds", "Time to plan a trip (MILP plus both baselines)",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))


def render() -> tuple[bytes, str]:
    """The current values in Prometheus' text format, plus its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
