"""Where rules, actions, approvals, autonomy settings and the audit log live, one business at a time.

    store = MemoryStore("brightdesk")                       # tests, offline demos
    store = PgStore("brightdesk", settings.database_url)    # Neon, row-level security per business

Both have the same methods and return the same plain dicts. Group writes that belong together:

    with store.tx():
        aid = store.add_action(...)
        store.audit("pheri", "approval_requested", "action", aid)

PgStore follows db/schema.sql's rule for Neon's pooled endpoint: the role and the tenant are set
with SET LOCAL / set_config(..., true) inside every transaction, never for the session, because
a pooled session is handed to other clients. It never queries as the table owner (neondb_owner
bypasses RLS). The audit log is append-only in both: there is no method to change or delete it.
"""

from __future__ import annotations

import copy
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Callable

from .synth import BUSINESS_IDS, NOW

ACTION_STATUSES = ("proposed", "blocked", "suggested", "awaiting_approval", "approved", "rejected", "executed",
                   "failed")


class NotFound(KeyError):
    pass


class MemoryStore:
    def __init__(self, business: str, clock: Callable[[], datetime] = lambda: NOW):
        self.business = business
        self.clock = clock
        self._rules: dict[str, dict] = {}
        self._actions: dict[str, dict] = {}
        self._approvals: dict[str, dict] = {}
        self._autonomy: dict[str, dict] = {}
        self._audit: list[dict] = []

    @contextmanager
    def tx(self):
        """All or nothing, like a database transaction: on error every change in the block is undone."""
        saved = copy.deepcopy((self._rules, self._actions, self._approvals, self._autonomy, self._audit))
        try:
            yield self
        except BaseException:
            self._rules, self._actions, self._approvals, self._autonomy, self._audit = saved
            raise

    # ---- audit (append-only) ----
    def audit(self, actor: str, event: str, subject_type: str | None = None, subject_id: str | None = None,
              details: dict | None = None) -> None:
        self._audit.append({"id": len(self._audit) + 1, "at": self.clock(), "actor": actor, "event": event,
                            "subject_type": subject_type, "subject_id": subject_id,
                            "details": copy.deepcopy(details or {})})

    def audit_log(self, subject_id: str | None = None) -> list[dict]:
        return [copy.deepcopy(a) for a in self._audit if subject_id is None or a["subject_id"] == subject_id]

    # ---- rules ----
    def add_rule(self, name: str, source_text: str, compiled: dict) -> str:
        rid = str(uuid.uuid4())
        self._rules[rid] = {"id": rid, "name": name, "source_text": source_text, "compiled": copy.deepcopy(compiled),
                            "active": False, "confirmed_by": None, "confirmed_at": None, "created_at": self.clock()}
        return rid

    def get_rule(self, rule_id: str) -> dict:
        if rule_id not in self._rules:
            raise NotFound(rule_id)
        return copy.deepcopy(self._rules[rule_id])

    def activate_rule(self, rule_id: str, by: str) -> None:
        self.get_rule(rule_id)
        self._rules[rule_id].update(active=True, confirmed_by=by, confirmed_at=self.clock())

    def rules(self, active_only: bool = True) -> list[dict]:
        return [copy.deepcopy(r) for r in self._rules.values() if r["active"] or not active_only]

    # ---- autonomy dial ----
    def autonomy_modes(self) -> dict[str, str]:
        return {k: v["mode"] for k, v in self._autonomy.items()}

    def set_autonomy(self, kind: str, mode: str, by: str) -> None:
        self._autonomy[kind] = {"mode": mode, "updated_by": by, "updated_at": self.clock()}

    # ---- actions ----
    def add_action(self, customer_key: str, kind: str, payload: dict, why: str, evidence: list, mode: str | None,
                   rule_check: dict, status: str) -> str:
        assert status in ACTION_STATUSES, status
        aid = str(uuid.uuid4())
        self._actions[aid] = {"id": aid, "customer_key": customer_key, "kind": kind, "payload": copy.deepcopy(payload),
                              "why": why, "evidence": copy.deepcopy(evidence), "mode": mode,
                              "rule_check": copy.deepcopy(rule_check), "status": status, "created_at": self.clock(),
                              "executed_at": None}
        return aid

    def get_action(self, action_id: str) -> dict:
        if action_id not in self._actions:
            raise NotFound(action_id)
        return copy.deepcopy(self._actions[action_id])

    def set_action(self, action_id: str, status: str, rule_check: dict | None = None,
                   executed_at: datetime | None = None) -> None:
        assert status in ACTION_STATUSES, status
        a = self._actions[self.get_action(action_id)["id"]]
        a["status"] = status
        if rule_check is not None:
            a["rule_check"] = copy.deepcopy(rule_check)
        if executed_at is not None:
            a["executed_at"] = executed_at

    def actions(self, customer_key: str | None = None) -> list[dict]:
        return [copy.deepcopy(a) for a in self._actions.values()
                if customer_key is None or a["customer_key"] == customer_key]

    # ---- approval queue ----
    def add_approval(self, action_id: str) -> str:
        if any(p["action_id"] == action_id for p in self._approvals.values()):
            raise ValueError(f"action {action_id} already has an approval")  # same as the UNIQUE in schema.sql
        pid = str(uuid.uuid4())
        self._approvals[pid] = {"id": pid, "action_id": action_id, "decision": "pending", "decided_by": None,
                                "note": None, "requested_at": self.clock(), "decided_at": None}
        return pid

    def get_approval(self, approval_id: str) -> dict:
        if approval_id not in self._approvals:
            raise NotFound(approval_id)
        return copy.deepcopy(self._approvals[approval_id])

    def decide_approval(self, approval_id: str, decision: str, by: str, note: str | None = None) -> None:
        p = self._approvals[self.get_approval(approval_id)["id"]]
        if p["decision"] != "pending":
            raise ValueError(f"approval {approval_id} was already {p['decision']}")
        p.update(decision=decision, decided_by=by, note=note, decided_at=self.clock())

    def approvals(self, pending_only: bool = True) -> list[dict]:
        return [copy.deepcopy(p) for p in self._approvals.values() if p["decision"] == "pending" or not pending_only]


class PgStore:
    """Postgres (Neon). Every method runs in the open `tx()` block, or in a transaction of its own."""

    def __init__(self, business: str, url: str, schema: str | None = None):
        self.business = business
        self.business_id = BUSINESS_IDS[business]
        self.url = url
        self.schema = schema  # tests use a throwaway schema
        self._conn = None  # kept open between transactions: a new connection to Neon costs seconds
        self._con = None  # set while a transaction is open

    def _connection(self):
        import psycopg

        if self._conn is None or self._conn.closed or self._conn.broken:
            # autocommit: nothing runs outside an explicit transaction block, so no setting can outlive one.
            # prepare_threshold=None: no server-side prepared statements, which a pooled session can't keep.
            self._conn = psycopg.connect(self.url, autocommit=True, prepare_threshold=None)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def tx(self):
        if self._con is not None:  # already inside a transaction: join it
            yield self
            return
        con = self._connection()
        with con.transaction():
            # Role, tenant and schema are LOCAL (third argument true): they end with this transaction.
            con.execute("SELECT set_config('role', 'pheri_app', true), set_config('app.business_id', %s, true), "
                        "set_config('search_path', COALESCE(%s, current_setting('search_path')), true)",
                        (self.business_id, f'"{self.schema}"' if self.schema else None))
            self._con = con
            try:
                yield self
            finally:
                self._con = None

    def _q(self, sql: str, params=()) -> list[dict]:
        from psycopg.rows import dict_row

        with self.tx():
            cur = self._con.cursor(row_factory=dict_row)
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []

    @staticmethod
    def _json(v):
        from psycopg.types.json import Jsonb

        return Jsonb(v)

    @staticmethod
    def _one(rows: list[dict], what: str) -> dict:
        if not rows:
            raise NotFound(what)
        return rows[0]

    # ---- audit (append-only: the app role has only SELECT and INSERT) ----
    def audit(self, actor, event, subject_type=None, subject_id=None, details=None) -> None:
        self._q("INSERT INTO audit_log (business_id, actor, event, subject_type, subject_id, details) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (self.business_id, actor, event, subject_type, subject_id, self._json(details or {})))

    def audit_log(self, subject_id=None) -> list[dict]:
        sql = "SELECT id, at, actor, event, subject_type, subject_id, details FROM audit_log"
        if subject_id is None:
            return self._q(sql + " ORDER BY id")
        return self._q(sql + " WHERE subject_id = %s ORDER BY id", (subject_id,))

    # ---- rules ----
    def add_rule(self, name, source_text, compiled) -> str:
        return str(self._q("INSERT INTO rules (business_id, name, source_text, compiled) VALUES (%s, %s, %s, %s) "
                           "RETURNING id", (self.business_id, name, source_text, self._json(compiled)))[0]["id"])

    _RULE = "SELECT id::text, name, source_text, compiled, active, confirmed_by, confirmed_at, created_at FROM rules"

    def get_rule(self, rule_id) -> dict:
        return self._one(self._q(self._RULE + " WHERE id = %s", (rule_id,)), rule_id)

    def activate_rule(self, rule_id, by) -> None:
        if not self._q("UPDATE rules SET active = true, confirmed_by = %s, confirmed_at = now() WHERE id = %s "
                       "RETURNING id", (by, rule_id)):
            raise NotFound(rule_id)

    def rules(self, active_only=True) -> list[dict]:
        return self._q(self._RULE + (" WHERE active" if active_only else "") + " ORDER BY created_at, id")

    # ---- autonomy dial ----
    def autonomy_modes(self) -> dict[str, str]:
        return {r["action_kind"]: r["mode"] for r in self._q("SELECT action_kind, mode FROM autonomy")}

    def set_autonomy(self, kind, mode, by) -> None:
        self._q("INSERT INTO autonomy (business_id, action_kind, mode, updated_by) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (business_id, action_kind) DO UPDATE SET mode = EXCLUDED.mode, "
                "updated_by = EXCLUDED.updated_by, updated_at = now()", (self.business_id, kind, mode, by))

    # ---- actions ----
    def _customer_id(self, key: str) -> str:
        # Upsert so an action can always name its customer; the no-op update makes RETURNING work on conflict.
        return self._q("INSERT INTO customers (business_id, email) VALUES (%s, %s) "
                       "ON CONFLICT (business_id, email) DO UPDATE SET email = EXCLUDED.email RETURNING id",
                       (self.business_id, key))[0]["id"]

    def add_action(self, customer_key, kind, payload, why, evidence, mode, rule_check, status) -> str:
        with self.tx():
            cid = self._customer_id(customer_key)
            return str(self._q(
                "INSERT INTO actions (business_id, customer_id, kind, payload, why, evidence, mode, rule_check, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (self.business_id, cid, kind, self._json(payload), why, self._json(evidence), mode,
                 self._json(rule_check), status))[0]["id"])

    _ACTION = ("SELECT a.id::text, c.email AS customer_key, a.kind, a.payload, a.why, a.evidence, a.mode, "
               "a.rule_check, a.status, a.created_at, a.executed_at FROM actions a JOIN customers c ON c.id = a.customer_id")

    def get_action(self, action_id) -> dict:
        return self._one(self._q(self._ACTION + " WHERE a.id = %s", (action_id,)), action_id)

    def set_action(self, action_id, status, rule_check=None, executed_at=None) -> None:
        rows = self._q("UPDATE actions SET status = %s, rule_check = COALESCE(%s, rule_check), "
                       "executed_at = COALESCE(%s, executed_at) WHERE id = %s RETURNING id",
                       (status, None if rule_check is None else self._json(rule_check), executed_at, action_id))
        if not rows:
            raise NotFound(action_id)

    def actions(self, customer_key=None) -> list[dict]:
        if customer_key is None:
            return self._q(self._ACTION + " ORDER BY a.created_at, a.id")
        return self._q(self._ACTION + " WHERE c.email = %s ORDER BY a.created_at, a.id", (customer_key,))

    # ---- approval queue ----
    _APPROVAL = "SELECT id::text, action_id::text, decision, decided_by, note, requested_at, decided_at FROM approvals"

    def add_approval(self, action_id) -> str:
        return str(self._q("INSERT INTO approvals (business_id, action_id) VALUES (%s, %s) RETURNING id",
                           (self.business_id, action_id))[0]["id"])

    def get_approval(self, approval_id) -> dict:
        return self._one(self._q(self._APPROVAL + " WHERE id = %s", (approval_id,)), approval_id)

    def decide_approval(self, approval_id, decision, by, note=None) -> None:
        with self.tx():
            current = self._one(self._q(self._APPROVAL + " WHERE id = %s FOR UPDATE", (approval_id,)), approval_id)
            if current["decision"] != "pending":
                raise ValueError(f"approval {approval_id} was already {current['decision']}")
            self._q("UPDATE approvals SET decision = %s, decided_by = %s, note = %s, decided_at = now() WHERE id = %s",
                    (decision, by, note, approval_id))

    def approvals(self, pending_only=True) -> list[dict]:
        return self._q(self._APPROVAL + (" WHERE decision = 'pending'" if pending_only else "")
                       + " ORDER BY requested_at, id")
