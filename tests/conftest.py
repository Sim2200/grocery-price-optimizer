"""Shared test setup."""

import os

# Tracing is off in tests (no console span output); test_observability turns it on
# explicitly with an in-memory exporter.
os.environ["OTEL_TRACES_EXPORTER"] = "none"
