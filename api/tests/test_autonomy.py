"""Autonomy dial, approval queue and audit log, on the memory store and (when configured) real Postgres."""

from datetime import timedelta

import pytest

from conftest import PG_URL, throwaway_schema
from pheri.actions import ProposedAction
from pheri.autonomy import approve, modes, queue, reject, sent_messages, set_mode, submit
from pheri.rules import ChannelLimit, CheckContext
from pheri.store import MemoryStore, PgStore
from pheri.synth import BUSINESS_IDS, NOW

MAYA = "maya.okafor@pinecrest.example"
# Postgres round trips are slow from here (up to ~0.8 s each), so the real-database run covers the
# flows where the backend matters: writes, the approval round trip, history, rollback, the dial upsert.
BOTH = pytest.mark.parametrize("store", ["memory", "pg"], indirect=True)
HELP = ProposedAction(kind="send_help", channel="email", message="Here are the steps that fix the export.")
EVIDENCE = [{"ref": "failed_exports_30d", "value": "5"}]


@pytest.fixture(scope="module")
def pg_schema():
    if not PG_URL:
        pytest.skip("PHERI_TEST_DATABASE_URL not set: Postgres store tests skipped (memory store still ran)")
    pytest.importorskip("psycopg")
    with throwaway_schema() as pg:
        yield pg


@pytest.fixture
def store(request):
    """The memory store; tests marked with BOTH also run on real Postgres."""
    if getattr(request, "param", "memory") == "memory":
        yield MemoryStore("brightdesk")
        return
    psycopg, schema = request.getfixturevalue("pg_schema")
    # One schema per module (creating one takes seconds on Neon); each test starts with empty tables.
    # The audit log is append-only even here, so tests read it by subject id.
    with psycopg.connect(PG_URL) as con:
        con.execute(f'SET LOCAL search_path TO "{schema}"')
        con.execute("SELECT set_config('app.business_id', %s, true)", (BUSINESS_IDS["brightdesk"],))
        for table in ("approvals", "actions", "autonomy", "rules"):
            con.execute(f"DELETE FROM {table}")
    pg_store = PgStore("brightdesk", PG_URL, schema=schema)
    yield pg_store
    pg_store.close()


def ctx(store, key=MAYA, now=NOW):
    return CheckContext("brightdesk", {"days_since_signup": 22, "country": "UK"}, now, sent_messages(store, key))


def _submit(store, action=HELP, **kw):
    return submit(store, MAYA, action, ctx(store), why="Why this: stuck on exports", evidence=EVIDENCE, **kw)


def events(store, subject_id=None):
    return [a["event"] for a in store.audit_log(subject_id)]


def test_defaults_ask_the_owner_except_internal_tasks(store):
    dial = modes(store)
    assert dial["send_help"] == "ask_owner" and dial["offer_discount"] == "ask_owner"
    assert dial["task_for_owner"] == "act_alone"
    assert "no_action" not in dial


@BOTH
def test_set_mode_is_validated_and_audited(store):
    set_mode(store, "send_help", "act_alone", by="owner:aditi")
    assert modes(store)["send_help"] == "act_alone"
    entry = store.audit_log("send_help")[-1]
    assert entry["event"] == "autonomy_changed" and entry["details"] == {"from": "ask_owner", "to": "act_alone"}
    with pytest.raises(ValueError):
        set_mode(store, "send_help", "yolo", by="owner")
    with pytest.raises(ValueError):
        set_mode(store, "send_reminder", "act_alone", by="owner")  # a Kettle action


@BOTH
def test_ask_owner_queues_then_approval_executes(store):
    a = _submit(store)
    assert a["status"] == "awaiting_approval" and a["mode"] == "ask_owner" and a["executed_at"] is None
    assert a["evidence"] == EVIDENCE and a["payload"]["channel"] == "email"
    q = queue(store)
    assert [p["action"]["id"] for p in q] == [a["id"]]

    done = approve(store, q[0]["id"], by="owner:aditi", context_for=lambda key: ctx(store, key))
    assert done["status"] == "executed" and done["executed_at"] is not None
    assert queue(store) == []
    assert events(store, a["id"]) == ["rule_passed", "approval_requested", "approved", "executed"]
    assert store.audit_log(a["id"])[-1]["details"] == {"delivery": "simulated"}
    with pytest.raises(ValueError, match="already approved"):
        approve(store, q[0]["id"], by="owner:aditi", context_for=lambda key: ctx(store, key))
    assert events(store, a["id"]) == ["rule_passed", "approval_requested", "approved", "executed"]  # unchanged


def test_suggest_never_executes(store):
    set_mode(store, "send_help", "suggest", by="owner")
    a = _submit(store)
    assert a["status"] == "suggested" and queue(store) == []
    assert events(store, a["id"]) == ["rule_passed", "suggested"]


def test_act_alone_executes_at_once(store):
    set_mode(store, "send_help", "act_alone", by="owner")
    a = _submit(store)
    assert a["status"] == "executed" and queue(store) == []
    assert sent_messages(store, MAYA) == [("email", a["executed_at"])]


def test_weak_evidence_caps_the_dial_at_ask_owner(store):
    set_mode(store, "send_help", "act_alone", by="owner")
    assert _submit(store, cap="ask_owner")["status"] == "awaiting_approval"
    set_mode(store, "send_help", "suggest", by="owner")
    assert _submit(store, cap="ask_owner")["status"] == "suggested"  # a cap never adds autonomy


def test_blocked_action_goes_nowhere(store):
    a = _submit(store, ProposedAction(kind="offer_discount", channel="whatsapp", discount_pct=10))
    assert a["status"] == "blocked" and a["mode"] is None and queue(store) == []
    assert not a["rule_check"]["allowed"]
    assert events(store, a["id"]) == ["rule_blocked"]


@BOTH
def test_approval_rechecks_the_rules(store):
    a = _submit(store)
    pid = queue(store)[0]["id"]
    # While it waited, the owner added a rule: no email at all.
    rid = store.add_rule("no email", "Never email customers.",
                         {"checks": [ChannelLimit(channel="email", max_messages=0, per_days=1).model_dump()]})
    store.activate_rule(rid, "owner")
    done = approve(store, pid, by="owner:aditi", context_for=lambda key: ctx(store, key))
    assert done["status"] == "blocked" and done["executed_at"] is None
    assert events(store, a["id"])[-2:] == ["approved", "rule_blocked"]


@BOTH
def test_channel_limit_sees_actions_already_executed(store):
    rid = store.add_rule("one email", "One email a week.",
                         {"checks": [ChannelLimit(channel="email", max_messages=1, per_days=7).model_dump()]})
    store.activate_rule(rid, "owner")
    set_mode(store, "send_help", "act_alone", by="owner")
    assert _submit(store)["status"] == "executed"
    second = submit(store, MAYA, HELP, ctx(store, now=NOW + timedelta(hours=1)), why="", evidence=EVIDENCE)
    assert second["status"] == "blocked"


def test_reject(store):
    a = _submit(store)
    done = reject(store, queue(store)[0]["id"], by="owner:aditi", note="I'll call her myself")
    assert done["status"] == "rejected"
    assert store.audit_log(a["id"])[-1]["details"]["note"] == "I'll call her myself"


@BOTH
def test_failed_write_leaves_no_half_action(store):
    a = _submit(store)
    with pytest.raises(Exception):
        with store.tx():
            store.audit("pheri", "should_vanish", "action", a["id"])
            store.add_approval(a["id"])  # a second approval for the same action: refused
    assert "should_vanish" not in events(store, a["id"])
    assert len(store.approvals(pending_only=False)) == 1


def test_memory_store_hands_out_copies():
    store = MemoryStore("brightdesk")
    store.audit("pheri", "x", details={"k": 1})
    store.audit_log()[0]["details"]["k"] = 2
    assert store.audit_log()[0]["details"] == {"k": 1}


def test_pg_store_settings_never_outlive_a_transaction(request):
    """PgStore keeps its connection open; role and tenant must still end with each transaction."""
    _, schema = request.getfixturevalue("pg_schema")
    store = PgStore("brightdesk", PG_URL, schema=schema)
    try:
        with store.tx():
            inside = store._con.execute("SELECT current_user, current_setting('app.business_id', true)").fetchone()
        after = store._conn.execute("SELECT current_user, current_setting('app.business_id', true)").fetchone()
    finally:
        store.close()
    assert inside == ("pheri_app", BUSINESS_IDS["brightdesk"])
    assert after[0] != "pheri_app" and not after[1]
