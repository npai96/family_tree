from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BASE_DIR / "app" / "api" / "mvp.db"


@dataclass(frozen=True)
class DatabaseConfig:
    backend: str
    database_url: str
    sqlite_path: Path | None


def _normalize_sqlite_url(raw_url: str) -> Path:
    parsed = urlparse(raw_url)
    if parsed.scheme != "sqlite":
        raise ValueError(f"Unsupported sqlite URL: {raw_url}")

    if parsed.netloc and parsed.netloc != "localhost":
        raw_path = f"//{parsed.netloc}{parsed.path}"
    else:
        raw_path = parsed.path

    if not raw_path:
        raise ValueError("sqlite DATABASE_URL must include a file path")

    return Path(unquote(raw_path))


def build_database_config(database_url: str = "", db_path_env: str = "") -> DatabaseConfig:
    if database_url:
        if database_url.startswith("sqlite:///"):
            sqlite_path = _normalize_sqlite_url(database_url)
            return DatabaseConfig(backend="sqlite", database_url=database_url, sqlite_path=sqlite_path)

        if database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
            return DatabaseConfig(backend="postgres", database_url=database_url, sqlite_path=None)

        raise ValueError(f"Unsupported DATABASE_URL scheme in {database_url!r}")

    sqlite_path = Path(db_path_env) if db_path_env else DEFAULT_SQLITE_PATH
    return DatabaseConfig(
        backend="sqlite",
        database_url=f"sqlite://{sqlite_path}",
        sqlite_path=sqlite_path,
    )


def load_database_config() -> DatabaseConfig:
    return build_database_config(
        database_url=os.getenv("DATABASE_URL", "").strip(),
        db_path_env=os.getenv("DB_PATH", "").strip(),
    )
