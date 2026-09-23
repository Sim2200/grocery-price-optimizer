"""FastAPI REST API around the core package."""

from .app import create_app

__all__ = ["create_app"]
