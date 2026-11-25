"""Konfigurasi dari environment variable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # Koneksi terminal
    terminal_path: str | None = None
    login: int | None = None
    password: str | None = None
    server: str | None = None
    timeout_ms: int = 60_000

    # Pengaman eksekusi order
    trading_enabled: bool = False
    allow_real_account: bool = False
    max_lot: float = 1.0
    max_risk_percent: float = 2.0
    symbol_whitelist: frozenset[str] = field(default_factory=frozenset)

    # Default order
    magic: int = 20260204
    deviation: int = 20
    comment: str = "mcp-trading"

    @classmethod
    def from_env(cls) -> "Settings":
        login = os.environ.get("MT5_LOGIN")
        whitelist = os.environ.get("MT5_SYMBOL_WHITELIST", "")
        return cls(
            terminal_path=os.environ.get("MT5_PATH") or None,
            login=int(login) if login else None,
            password=os.environ.get("MT5_PASSWORD") or None,
            server=os.environ.get("MT5_SERVER") or None,
            timeout_ms=_int("MT5_TIMEOUT_MS", 60_000),
            trading_enabled=_bool("MT5_TRADING_ENABLED", False),
            allow_real_account=_bool("MT5_ALLOW_REAL_ACCOUNT", False),
            max_lot=_float("MT5_MAX_LOT", 1.0),
            max_risk_percent=_float("MT5_MAX_RISK_PERCENT", 2.0),
            symbol_whitelist=frozenset(
                s.strip().upper() for s in whitelist.split(",") if s.strip()
            ),
            magic=_int("MT5_MAGIC", 20260204),
            deviation=_int("MT5_DEVIATION", 20),
            comment=os.environ.get("MT5_COMMENT", "mcp-trading")[:31],
        )
