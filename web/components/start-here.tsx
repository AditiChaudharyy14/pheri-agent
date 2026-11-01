"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

/** For a first-time visitor: the demo's five moments in order, one line each. Dismissed once, it stays dismissed in
 * this browser (a convenience only: with storage blocked it simply shows again). Hidden on the server and until the
 * browser has read the choice, so a returning visitor never sees it flash. */

const KEY = "pheri:start-here:dismissed";
const listeners = new Set<() => void>();

function dismissed(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

function dismiss() {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    /* storage blocked: hidden until the page reloads */
  }
  hiddenThisPage = true;
  listeners.forEach((l) => l());
}

let hiddenThisPage = false;
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function StartHere({ business }: { business: string }) {
  const show = useSyncExternalStore(subscribe, () => !hiddenThisPage && !dismissed(), () => false);
  if (!show) return null;
  const b = `/${business}`;
  const steps = [
    { href: `${b}#brief`, title: "Morning brief", line: "What Pheri did overnight, in a few sentences, and what needs you." },
    { href: `${b}/night`, title: "Night shift", line: "Replay the night: every message read, every draft caught and rewritten." },
    { href: `${b}/slop`, title: "Slop vs Pheri", line: "A plain AI reply next to Pheri's, checked the same way." },
    { href: `${b}/rules#speak`, title: "Speak a rule", line: "Turn the owner's Hindi voice note into a rule and watch an offer get blocked." },
    { href: `${b}/proof`, title: "Proof", line: "Did it work, and is it safe? Measured against customers Pheri left alone." },
  ];
  return (
    <aside aria-labelledby="start-here" className="rounded-2xl border border-teal/30 bg-teal-soft/50 px-5 py-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="start-here" className="text-[1.1rem] font-medium text-ink">
          Start here: the demo in five steps
        </h2>
        <button onClick={dismiss} className="shrink-0 text-[0.9rem] text-muted underline underline-offset-4 hover:text-ink">
          Hide
        </button>
      </div>
      <ol className="mt-3 space-y-2">
        {steps.map((s, i) => (
          <li key={s.title} className="grid grid-cols-[1.5rem_1fr] gap-x-2 text-[0.95rem]">
            <span className="font-serif text-teal-ink">{i + 1}</span>
            <span>
              <Link href={s.href} className="font-medium text-teal-ink underline underline-offset-4">
                {s.title}
              </Link>
              <span className="text-ink-2"> · {s.line}</span>
            </span>
          </li>
        ))}
      </ol>
    </aside>
  );
}
