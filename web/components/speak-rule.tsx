"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { call, type RuleRow } from "@/lib/api";
import { actionLabel } from "@/lib/labels";

type Stopped = { action_id: string; customer: string; name: string; kind: string; reason: string };
type VoiceDraft = RuleRow & {
  transcript: string;
  clip: { clip: string; language: string; said: string; recorded: boolean };
  would_block: Stopped[];
};

/** Speak a rule: the owner's recorded voice note (no microphone here) is read by Muse Voice, compiled by the same
 * code as a typed rule, and shown before anything is enforced. Confirm, and every step still waiting is checked
 * against it again: the ones that break it are blocked, with the rule as the reason. */
export function SpeakRule({ business }: { business: string }) {
  const router = useRouter();
  const [draft, setDraft] = useState<VoiceDraft | null>(null);
  const [blocked, setBlocked] = useState<Stopped[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const read = () =>
    start(async () => {
      setError(null);
      setBlocked(null);
      try {
        setDraft(await call<VoiceDraft>(`/businesses/${business}/rules/voice`, { body: { clip: "owner-rule-hi", by: "owner:demo" } }));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  const confirm = () =>
    start(async () => {
      if (!draft) return;
      try {
        const r = await call<RuleRow & { blocked: Stopped[] }>(`/businesses/${business}/rules/${draft.id}/confirm`, {
          body: { by: "owner:demo" },
        });
        setBlocked(r.blocked);
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  return (
    <section aria-labelledby="speak-rule">
      <h2 id="speak-rule" className="text-[1.45rem] font-medium">Speak a rule</h2>
      <p className="mt-1 text-ink-2">
        Say a rule the way you would tell your staff. Muse Voice reads Hindi and English; this is your recorded voice note.
      </p>
      <audio controls preload="none" src="/voice/owner-rule-hi.wav" className="mt-3 w-full" aria-label="The owner's voice note" />
      <button
        onClick={read}
        disabled={pending}
        className="mt-3 rounded-xl bg-teal px-4 py-2.5 text-[0.95rem] font-medium text-white hover:bg-teal-ink disabled:opacity-60"
      >
        {pending && !draft ? "Reading the voice note…" : "Turn this voice note into a rule"}
      </button>
      {error && <p className="mt-2 text-[0.9rem] text-rose" role="alert">{error}</p>}

      {draft && (
        <div className="mt-4 space-y-3">
          <div>
            <p className="text-[0.82rem] text-muted">Muse Voice heard{draft.clip.recorded ? " (recorded from a live run)" : ""}:</p>
            <blockquote lang="hi" className="mt-1 border-l-2 border-line-2 pl-3 font-serif text-[1.1rem] leading-snug text-ink">
              {draft.transcript}
            </blockquote>
          </div>
          <div>
            <p className="text-[0.82rem] text-muted">What code will enforce:</p>
            {draft.described.length ? (
              <ul className="mt-1 list-disc pl-5 text-ink">
                {draft.described.map((d) => <li key={d}>{d}</li>)}
              </ul>
            ) : (
              <p className="mt-1 text-amber">Nothing code can enforce: {[...draft.problems, ...draft.unsupported].join("; ")}</p>
            )}
          </div>
          <p className="text-[0.92rem] text-ink-2">
            {draft.would_block.length
              ? `If you confirm, ${draft.would_block.length} waiting ${draft.would_block.length === 1 ? "step breaks" : "steps break"} it and will be blocked:`
              : "No step waiting tonight breaks it."}
          </p>
          {draft.would_block.length > 0 && (
            <ul className="space-y-1 text-[0.92rem]">
              {draft.would_block.map((x) => (
                <li key={x.action_id}><b className="font-medium">{x.name}</b> · {actionLabel(x.kind)}: {x.reason}</li>
              ))}
            </ul>
          )}
          {blocked === null && draft.confirmable && (
            <button
              onClick={confirm}
              disabled={pending}
              className="rounded-xl border-2 border-teal px-4 py-2 text-[0.95rem] font-medium text-teal-ink hover:bg-teal-soft disabled:opacity-60"
            >
              Confirm the rule
            </button>
          )}
          {blocked !== null && (
            <div role="status" className="rounded-lg bg-teal-soft px-3 py-2 text-[0.92rem] text-ink">
              <p className="font-medium text-teal-ink">✓ In force from now on.</p>
              {blocked.length ? (
                <ul className="mt-1 space-y-0.5">
                  {blocked.map((x) => (
                    <li key={x.action_id}>
                      <span className="text-rose">Blocked by your rule, your new one:</span> {x.name}, {actionLabel(x.kind).toLowerCase()}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1">Nothing waiting broke it, so nothing changed.</p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
