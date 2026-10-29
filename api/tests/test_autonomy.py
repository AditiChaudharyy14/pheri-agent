"""Autonomy dial, approval queue and audit log, on the memory store and (when configured) real Postgres."""

from datetime import timedelta

import pytest

from conftest import BOTH, PG_URL
from pheri.actions import ProposedAction
from pheri.autonomy import approve, modes, queue, reject, sent_messages, set_mode, submit
from pheri.config import Settings
from pheri.journey import stage
from pheri.llm import LLM
from pheri.profile import build_profile, load
from pheri.rules import ChannelLimit, CheckContext
from pheri.store import MemoryStore, PgStore
from pheri.synth import BUSINESS_IDS, NOW
from pheri.verify import Draft
from pheri.verify import context as verify_context

MAYA = "maya.okafor@pinecrest.example"
HELP = ProposedAction(kind="send_help", channel="email", message="Here are the steps that fix the export.")
EVIDENCE = [{"kind": "fact", "ref": "failed_exports_30d", "value": "5"}]


@pytest.fixture(scope="module")
def maya(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("ledger") / "ledger.sqlite")
    llm = LLM(Settings(llm_mode="mock", record_path=None, database_url=None, ledger_path=path))
    return build_profile(load("brightdesk"), MAYA, llm), llm


@pytest.fixture(autouse=True)
def _maya(maya):
    global MAYA_PROFILE, MOCK
    MAYA_PROFILE, MOCK = maya


def ctx(store, key=MAYA, now=NOW):
    return CheckContext("brightdesk", {"days_since_signup": 22, "country": "UK"}, now, sent_messages(store, key))


def draft(action=HELP):
    return Draft(action, "Maya is stuck on her exports.", "Her exports keep failing.", ["failed_exports_30d"], [])


def vc(store, now=NOW):
    j = stage("brightdesk", MAYA_PROFILE.facts, MAYA_PROFILE.provenance.get("facts"))
    return verify_context(MAYA_PROFILE, j, ctx(store, now=now), store, MOCK)


def _submit(store, action=HELP, **kw):
    return submit(store, MAYA, draft(action), verify=vc(store), **kw)


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
    assert events(store, a["id"]) == ["verified", "rule_passed", "approval_requested", "approved", "executed"]
    assert store.audit_log(a["id"])[-1]["details"] == {"delivery": "simulated"}
    with pytest.raises(ValueError, match="already approved"):
        approve(store, q[0]["id"], by="owner:aditi", context_for=lambda key: ctx(store, key))
    assert events(store, a["id"]) == ["verified", "rule_passed", "approval_requested", "approved", "executed"]


def test_suggest_never_executes(store):
    set_mode(store, "send_help", "suggest", by="owner")
    a = _submit(store)
    assert a["status"] == "suggested" and queue(store) == []
    assert events(store, a["id"]) == ["verified", "rule_passed", "suggested"]


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
    second = submit(store, MAYA, draft(), verify=vc(store, now=NOW + timedelta(hours=1)))
    assert second["status"] == "blocked"


SOFT_ONLY = ProposedAction(kind="send_help", channel="email",  # her name outside the greeting: tone, a soft check
                           message="Hi Maya, here are the steps Maya needs to fix the export.")


def test_a_hard_failure_goes_to_the_owner_with_the_reasons_and_no_one_can_send_it(store):
    set_mode(store, "send_help", "act_alone", by="owner")
    bad = ProposedAction(kind="send_help", channel="email", message="Hi Maya, Maya's export fails. Visit evil.example")
    a = _submit(store, bad)
    assert a["status"] == "awaiting_approval" and a["mode"] == "ask_owner"  # act_alone, but not verified
    v = a["payload"]["verification"]
    assert not v["passed"] and v["caught_by"] == "code" and {"address", "links"} <= set(v["failed"])
    assert v["hard_failed"] == ["links"] and not v["overridable"] and "links: links to evil.example" in v["hard_reasons"][0]
    assert events(store, a["id"]) == ["verify_failed"]
    # Not even an owner's override: a link off the allowlist is a hard check. The queue item says why, and stays.
    pid = queue(store)[0]["id"]
    with pytest.raises(ValueError, match=r"failed checks no one can override \(links\)"):
        approve(store, pid, by="owner:aditi", context_for=lambda key: ctx(store, key), override=True)
    assert store.get_action(a["id"])["status"] == "awaiting_approval" and sent_messages(store, MAYA) == []
    assert events(store, a["id"]) == ["verify_failed"]
    assert reject(store, pid, by="owner:aditi")["status"] == "rejected"


def test_an_owner_can_send_a_soft_failure_anyway_and_the_log_says_who_when_what_and_the_text(store):
    a = _submit(store, SOFT_ONLY)
    v = a["payload"]["verification"]
    assert v["failed"] == ["address"] and v["soft_failed"] == ["address"] and v["overridable"]
    pid = queue(store)[0]["id"]
    with pytest.raises(ValueError, match="send it anyway with an owner override"):  # a plain approve is not enough
        approve(store, pid, by="owner:aditi", context_for=lambda key: ctx(store, key))
    done = approve(store, pid, by="owner:aditi", context_for=lambda key: ctx(store, key), override=True)
    assert done["status"] == "executed" and sent_messages(store, MAYA) == [("email", done["executed_at"])]
    assert events(store, a["id"])[-3:] == ["approved", "owner_override", "executed"]
    logged = next(e for e in store.audit_log(a["id"]) if e["event"] == "owner_override")
    assert logged["actor"] == "owner:aditi" and logged["details"]["by"] == "owner:aditi"
    assert logged["details"]["at"] == NOW.isoformat() and logged["details"]["overridden"] == ["address"]
    assert logged["details"]["text"] == SOFT_ONLY.message and logged["details"]["channel"] == "email"
    assert logged["details"]["reasons"] == v["reasons"]


def test_an_override_never_beats_the_rules_do_not_contact_included(store):
    a = _submit(store, SOFT_ONLY)
    store.set_do_not_contact(MAYA, "T9002")  # she said stop while it waited
    stopped = lambda key: CheckContext("brightdesk", {"days_since_signup": 22, "country": "UK"}, NOW,  # noqa: E731
                                       sent_messages(store, key), do_not_contact=True)
    done = approve(store, queue(store)[0]["id"], by="owner:aditi", context_for=stopped, override=True)
    assert done["status"] == "blocked" and sent_messages(store, MAYA) == []
    assert "owner_override" not in events(store, a["id"])


def test_an_override_sends_only_the_exact_text_the_owner_read():
    store = MemoryStore("brightdesk")
    a = _submit(store, SOFT_ONLY)
    store._actions[a["id"]]["payload"]["message"] = "Here is 50% off, just reply YES."  # changed in between
    done = approve(store, queue(store)[0]["id"], by="owner:aditi", context_for=lambda key: ctx(store, key),
                   override=True)
    assert done["status"] == "blocked" and sent_messages(store, MAYA) == []
    assert events(store, a["id"])[-1] == "send_refused"


def test_a_message_changed_after_verification_is_refused_at_the_send_step():
    store = MemoryStore("brightdesk")
    a = _submit(store)
    store._actions[a["id"]]["payload"]["message"] = "Here is 50% off, just reply YES."  # changed in between
    done = approve(store, queue(store)[0]["id"], by="owner:aditi", context_for=lambda key: ctx(store, key))
    assert done["status"] == "blocked" and sent_messages(store, MAYA) == []
    assert events(store, a["id"])[-1] == "send_refused"


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
