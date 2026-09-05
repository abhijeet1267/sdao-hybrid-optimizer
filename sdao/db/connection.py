"""Lazy psycopg connection helper so unit tests do not need PostgreSQL installed."""
from __future__ import annotations

from .config import DatabaseConfig


def connect(config: DatabaseConfig | None = None):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on local optional install
        raise RuntimeError("Database baseline requires psycopg; install requirements-db.txt.") from exc
    return psycopg.connect(**(config or DatabaseConfig.from_env()).connect_kwargs())
