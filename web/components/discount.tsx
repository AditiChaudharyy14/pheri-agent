"use client";

import { useState, useTransition } from "react";
import { call, customerPath, type DiscountCheck } from "@/lib/api";

/** "Offer a discount": the owner's rules decide in code, and a refusal says which rule, in its own words. */
export function OfferDiscount({ business, customerKey, name }: { business: string; customerKey: string; name: string }) {
  const [pct, setPct] = useState(10);
  const [result, setResult] = useState<DiscountCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const check = () =>
    start(async () => {
      setError(null);
      try {
        setResult(await call<DiscountCheck>(`${customerPath(business, customerKey)}/discount-check`, { body: { discount_pct: pct } }));
      } catch (e) {
        setResult(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  return (
    <div>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-ink-2">
          <input
            type="number"
            min={1}
            max={100}
            value={pct}
            onChange={(e) => setPct(Number(e.target.value))}
            className="w-20 rounded-lg border border-line-2 bg-paper px-3 py-2 text-right text-ink"
            aria-label="Discount, percent"
          />
          % off
        </label>
        <button
          onClick={check}
          disabled={pending}
          className="flex-1 rounded-xl border border-teal bg-surface px-4 py-2.5 font-medium text-teal-ink hover:bg-teal-soft disabled:opacity-60"
        >
          Offer a discount
        </button>
      </div>
      {error && <p className="mt-3 text-[0.92rem] text-rose">{error}</p>}
      {result && !result.allowed && (
        <div className="mt-4 rounded-xl border border-rose/25 bg-rose-soft p-4" role="status">
          <p className="font-medium text-rose">Refused. Pheri will not offer {name} {pct}% off.</p>
          {result.refused_by.map((r) => (
            <div key={r.rule_id} className="mt-3">
              {r.source_text && <p className="font-serif text-[1.1rem] text-ink">&ldquo;{r.source_text}&rdquo;</p>}
              <p className="mt-1 text-[0.95rem] text-ink-2">{r.described.join(" ")}</p>
              <p className="mt-1 text-[0.92rem] text-muted">Here: {r.reason}.</p>
            </div>
          ))}
        </div>
      )}
      {result?.allowed && (
        <div className="mt-4 rounded-xl border border-teal/25 bg-teal-soft p-4" role="status">
          <p className="font-medium text-teal-ink">Every rule allows {pct}% off for {name}.</p>
          <p className="mt-1 text-[0.92rem] text-ink-2">It would still wait for your approval before anything is sent.</p>
        </div>
      )}
    </div>
  );
}
