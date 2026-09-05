"""Credential-free configuration for the optional PostgreSQL baseline."""
from __future__ import annotations

from dataclasses import dataclass
import os


class ConfigurationError(ValueError):
    """Raised when required database configuration is absent or invalid."""


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "DatabaseConfig":
        if environ is None:
            try:
                from dotenv import load_dotenv
            except ImportError as exc:  # pragma: no cover - depends on optional install
                raise RuntimeError("Database configuration from .env requires python-dotenv; install requirements-db.txt.") from exc
            load_dotenv(override=False)
        values = os.environ if environ is None else environ
        names = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
        missing = [name for name in names if not values.get(name)]
        if missing:
            raise ConfigurationError("Missing required PostgreSQL environment variable(s): " + ", ".join(missing))
        try:
            port = int(values["POSTGRES_PORT"])
        except ValueError as exc:
            raise ConfigurationError("POSTGRES_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ConfigurationError("POSTGRES_PORT must be between 1 and 65535")
        return cls(values["POSTGRES_HOST"], port, values["POSTGRES_DB"], values["POSTGRES_USER"], values["POSTGRES_PASSWORD"])

    def connect_kwargs(self) -> dict[str, str | int]:
        return {"host": self.host, "port": self.port, "dbname": self.database, "user": self.user, "password": self.password}
