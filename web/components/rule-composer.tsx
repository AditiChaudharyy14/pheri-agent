"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { call, type RuleRow } from "@/lib/api";

const EXAMPLES = [
  "No discounts above 15%",
  "Don't message anyone between 9pm and 8am",
  "No more than two emails a week",
  "Always be polite to customers.",
];

/** Type a rule, see exactly what code will enforce, then confirm it. Nothing is enforced before Confirm. */
export function RuleComposer({ business }: { business: string }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<RuleRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const preview = () =>
    start(async () => {
      setError(null);
      setDone(null);
      try {
        setDraft(await call<RuleRow>(`/businesses/${business}/rules`, { body: { text, by: "owner:demo" } }));
      } catch (e) {
        setDraft(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  const confirm = () =>
    start(async () => {
      if (!draft) return;
      try {
        await call(`/businesses/${business}/rules/${draft.id}/confirm`, { body: { by: "owner:demo" } });
        setDone(draft.source_text);
        setDraft(null);
        setText("");
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  return (
    <div>
      <label htmlFor="rule" className="block text-[1.05rem] text-ink-2">
        Write a rule the way you would say it
      </label>
      <div className="mt-3 flex gap-3">
        <input
          id="rule"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setDraft(null);
          }}
          onKeyDown={(e) => e.key === "Enter" && text.trim() && preview()}
          placeholder="e.g. No discounts above 15%"
          className="min-w-0 flex-1 rounded-xl border border-line-2 bg-paper px-4 py-3 text-[1.05rem] text-ink placeholder:text-muted"
        />
        <button
          onClick={preview}
          disabled={pending || !text.trim()}
          className="rounded-xl bg-ink px-6 py-3 font-medium text-paper hover:bg-ink-2 disabled:opacity-50"
        >
          Preview
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((x) => (
          <button
            key={x}
            onClick={() => {
              setText(x);
              setDraft(null);
            }}
            className="rounded-full border border-line px-3 py-1 text-[0.88rem] text-ink-2 hover:bg-sunk"
          >
            {x}
          </button>
        ))}
      </div>

      {error && <p className="mt-4 text-rose">{error}</p>}
      {done && (
        <p className="mt-5 rounded-xl bg-teal-soft px-4 py-3 text-teal-ink" role="status">
          Confirmed and enforced from now on: &ldquo;{done}&rdquo;
        </p>
      )}

      {draft && (
        <div className="mt-6 rounded-2xl border border-line bg-paper p-6" role="status">
          <div className="text-[0.78rem] font-medium tracking-[0.08em] text-muted uppercase">What code will enforce</div>
          {draft.described.length ? (
            <ul className="mt-3 space-y-2">
              {draft.described.map((d) => (
                <li key={d} className="flex items-baseline gap-2.5 text-[1.1rem] text-ink">
                  <span className="text-teal">●</span>
                  {d}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-ink-2">Nothing code can check.</p>
          )}
          {draft.unsupported.length > 0 && (
            <p className="mt-4 rounded-lg bg-amber-soft px-3 py-2 text-amber">
              Pheri cannot enforce this in code: &ldquo;{draft.unsupported.join("; ")}&rdquo;. Rephrase it as a limit on
              discounts, hours or messages.
            </p>
          )}
          {draft.problems.length > 0 && (
            <p className="mt-4 rounded-lg bg-rose-soft px-3 py-2 text-rose">Could not compile: {draft.problems.join("; ")}</p>
          )}
          <div className="mt-5 flex items-center gap-3">
            <button
              onClick={confirm}
              disabled={pending || !draft.confirmable}
              className="rounded-xl bg-teal px-6 py-2.5 font-medium text-white hover:bg-teal-ink disabled:cursor-not-allowed disabled:opacity-40"
            >
              Confirm
            </button>
            <span className="text-[0.92rem] text-muted">
              {draft.confirmable ? "Not enforced until you confirm." : "Nothing to confirm yet."}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
