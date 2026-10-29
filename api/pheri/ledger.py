"""Spend ledger: every model call reserves its worst-case cost before it runs.

A call is refused if (settled + reserved + this estimate) would pass the provider's cap.
After the call, the reservation is settled with the real cost from the usage report,
or released if the call failed. Postgres is used when DATABASE_URL is set (shared by
laptop and server, so the cap is global); otherwise a local SQLite file.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, get_settings


class SpendCapExceeded(RuntimeError):
    """Raised before a call would push spend past the cap. Nothing was sent."""


@dataclass
class Totals:
    provider: str
    settled_usd: float
    reserved_usd: float
    offset_usd: float
    cap_usd: float

    @property
    def committed_usd(self) -> float:
        return self.settled_usd + self.reserved_usd + self.offset_usd

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.cap_usd - self.committed_usd)


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS spend_ledger (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,           -- reserved | settled | released
    estimate_usd REAL NOT NULL,
    actual_usd REAL,
    input_tokens INTEGER,
    cached_tokens INTEGER,
    output_tokens INTEGER,
    gpu_seconds REAL                -- open weights on our own GPU (Modal): billed per second, not per token
);
"""


class Ledger:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._pg = bool(self.settings.database_url)
        if not self._pg:
            Path(self.settings.ledger_path).parent.mkdir(parents=True, exist_ok=True)
            with self._sqlite() as con:
                con.executescript(_SCHEMA_SQLITE)
                # A ledger made before GPU-seconds were tracked keeps its rows and gains the column.
                if "gpu_seconds" not in {r[1] for r in con.execute("PRAGMA table_info(spend_ledger)")}:
                    con.execute("ALTER TABLE spend_ledger ADD COLUMN gpu_seconds REAL")

    # ---- storage -------------------------------------------------------
    @contextmanager
    def _sqlite(self):
        con = sqlite3.connect(self.settings.ledger_path, timeout=30, isolation_level=None)
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def _tx(self):
        """One exclusive transaction: no two processes can reserve at the same time."""
        if self._pg:
            import psycopg

            with psycopg.connect(self.settings.database_url) as con:
                with con.transaction():
                    con.execute("SELECT pg_advisory_xact_lock(424242)")
                    yield _PgCursor(con)
        else:
            with self._lock, self._sqlite() as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    yield _SqliteCursor(con)
                    con.execute("COMMIT")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise

    # ---- caps ----------------------------------------------------------
    def cap_for(self, provider: str) -> float:
        return {
            "meta": self.settings.meta_cap_usd,
            "baseten": self.settings.baseten_cap_usd,
            "modal": self.settings.modal_cap_usd,
        }.get(provider, 0.0)

    def offset_for(self, provider: str) -> float:
        return self.settings.meta_offset_usd if provider == "meta" else 0.0

    def _totals(self, cur, provider: str) -> Totals:
        settled = cur.scalar(
            "SELECT COALESCE(SUM(actual_usd), 0) FROM spend_ledger WHERE provider = %s AND status = 'settled'",
            (provider,),
        )
        reserved = cur.scalar(
            "SELECT COALESCE(SUM(estimate_usd), 0) FROM spend_ledger WHERE provider = %s AND status = 'reserved'",
            (provider,),
        )
        return Totals(provider, float(settled), float(reserved), self.offset_for(provider), self.cap_for(provider))

    def totals(self, provider: str) -> Totals:
        with self._tx() as cur:
            return self._totals(cur, provider)

    def breakdown(self) -> list[dict]:
        """Settled calls and their cost, per provider, model and purpose (costliest first)."""
        with self._tx() as cur:
            rows = cur.execute(
                "SELECT provider, model, purpose, COUNT(*), SUM(actual_usd), SUM(input_tokens), "
                "SUM(cached_tokens), SUM(output_tokens) FROM spend_ledger WHERE status = 'settled' "
                "GROUP BY provider, model, purpose ORDER BY SUM(actual_usd) DESC").fetchall()
        keys = ("provider", "model", "purpose", "calls", "usd", "input_tokens", "cached_tokens", "output_tokens")
        return [dict(zip(keys, (*r[:4], round(float(r[4] or 0), 6), *(int(v or 0) for v in r[5:])))) for r in rows]

    # ---- lifecycle -----------------------------------------------------
    def reserve(self, provider: str, model: str, purpose: str, estimate_usd: float) -> str:
        with self._tx() as cur:
            t = self._totals(cur, provider)
            if t.committed_usd + estimate_usd > t.cap_usd:
                raise SpendCapExceeded(
                    f"{provider} spend cap reached: committed ${t.committed_usd:.4f} + this call "
                    f"${estimate_usd:.4f} > cap ${t.cap_usd:.2f}. Nothing was sent."
                )
            rid = uuid.uuid4().hex
            cur.execute(
                "INSERT INTO spend_ledger (id, created_at, provider, model, purpose, status, estimate_usd) "
                "VALUES (%s, %s, %s, %s, %s, 'reserved', %s)",
                (rid, time.time(), provider, model, purpose, estimate_usd),
            )
            return rid

    def settle(self, rid: str, actual_usd: float, input_tokens: int, cached_tokens: int, output_tokens: int,
               gpu_seconds: float | None = None) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE spend_ledger SET status = 'settled', actual_usd = %s, input_tokens = %s, "
                "cached_tokens = %s, output_tokens = %s, gpu_seconds = %s WHERE id = %s",
                (actual_usd, input_tokens, cached_tokens, output_tokens, gpu_seconds, rid),
            )

    def gpu_seconds(self, provider: str = "modal") -> float:
        """GPU-seconds settled for a provider billed by the second (compare with its dashboard)."""
        with self._tx() as cur:
            return float(cur.scalar("SELECT COALESCE(SUM(gpu_seconds), 0) FROM spend_ledger "
                                    "WHERE provider = %s AND status = 'settled'", (provider,)))

    def release(self, rid: str) -> None:
        with self._tx() as cur:
            cur.execute("UPDATE spend_ledger SET status = 'released' WHERE id = %s", (rid,))


class _SqliteCursor:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def execute(self, sql: str, params=()):
        return self.con.execute(sql.replace("%s", "?"), params)

    def scalar(self, sql: str, params=()):
        return self.execute(sql, params).fetchone()[0]


class _PgCursor:
    def __init__(self, con):
        self.con = con

    def execute(self, sql: str, params=()):
        return self.con.execute(sql, params)

    def scalar(self, sql: str, params=()):
        return self.con.execute(sql, params).fetchone()[0]
