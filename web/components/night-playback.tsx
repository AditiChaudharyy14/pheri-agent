"use client";

import Link from "next/link";
import { useEffect, useMemo, useReducer, useState, useSyncExternalStore } from "react";
import type { NightEvent } from "@/lib/api";
import { actionLabel, clockNPT, LANGUAGE_NAME } from "@/lib/labels";

/** Replays the recorded night. Messages arrive on a clock that ticks from 21:00 to 06:00 (Nepal time), at the time
 * each one came in; at 06:15 the night shift runs (as it really does) and each row ticks through its steps: read,
 * every draft (caught and rewritten, or passed), and where it ended up. It opens finished, so the whole night is
 * readable without playing it; a device that asks for less motion never animates. Nothing here is invented: every
 * step is the stored decision. */

const NIGHT_MIN = 9 * 60; // 21:00 -> 06:00
const ARRIVE_MS = 24_000; // the arrivals, at 1x
const STEP_MS = 700; // one step of the night shift, at 1x
const TICK_MS = 100;

type Tone = "teal" | "marigold" | "vermilion" | "slate";
type Step = { text: string; tone: Tone; note?: string; lang?: string };

const DOT: Record<Tone, string> = { teal: "bg-teal", marigold: "bg-marigold", vermilion: "bg-vermilion", slate: "bg-line-2" };
const TEXT: Record<Tone, string> = { teal: "text-teal-ink", marigold: "text-amber", vermilion: "text-rose", slate: "text-ink-2" };

/** Minutes after 21:00 Nepal time (UTC+5:45). */
function minuteOfNight(at: string | null): number {
  if (!at) return 0;
  const d = new Date(at);
  const npt = (d.getUTCHours() * 60 + d.getUTCMinutes() + 345) % 1440;
  return (npt - 21 * 60 + 1440) % 1440;
}

function clockText(minute: number): string {
  const m = (21 * 60 + Math.round(minute)) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

function tone(e: NightEvent): Tone {
  if (e.outcome === "stopped" || e.outcome === "blocked") return "vermilion";
  if (e.outcome === "awaiting_approval" || e.action === "task_for_owner") return "marigold";
  if (e.outcome === "scheduled" || e.outcome === "executed") return "teal";
  return "slate";
}

function outcome(e: NightEvent): string {
  if (e.outcome === "stopped")
    return e.holding_reply
      ? `Stopped: it tried to trick Pheri. No model writes to them: a fixed reply written by code goes out at ${e.holding_reply.sends_at_local ?? "08:00"} their time, and the rest waits for you.`
      : "Stopped: it tried to trick Pheri. Nothing was done; it waits for you.";
  if (e.outcome === "blocked") return "Blocked by your rule: they asked not to be contacted. Nothing sent, no model asked.";
  if (e.outcome === "awaiting_approval") return `Waits for you: ${actionLabel(e.action).toLowerCase()}. ${e.waits_for_owner ?? ""}`;
  if (e.outcome === "scheduled") return `${actionLabel(e.action)}, checked, goes out at ${e.sends_at_local ?? "08:00"} their time.`;
  if (e.action === "task_for_owner") return "A task for you.";
  return actionLabel(e.action) || "Nothing to do.";
}

/** The row's steps, in order, from the stored decision. */
function steps(e: NightEvent): Step[] {
  const lang = LANGUAGE_NAME[e.lang ?? ""] ?? e.lang ?? "";
  const out: Step[] = [];
  if (e.kind === "voice_note" && !e.text) out.push({ text: `A voice note in ${lang}: Muse Voice can't read it yet, so it waits for you.`, tone: "marigold" });
  else out.push({ text: `Read${e.kind === "voice_note" ? " (voice note)" : ""}: ${lang}.`, tone: "slate" });
  e.drafts.forEach((d, i) =>
    out.push(
      d.passed
        ? { text: `Draft ${d.attempt}: passed every check.`, tone: "teal" }
        : {
            text: `Draft ${d.attempt} caught by ${d.caught_by === "judge" ? "the judge" : "code"}${d.reasons[0] ? `: ${d.reasons[0]}` : ""}${i < e.drafts.length - 1 ? " → sent back, rewritten." : ""}`,
            tone: "vermilion",
          },
    ),
  );
  out.push({
    text: outcome(e),
    tone: tone(e),
    note: e.holding_reply?.message,
    lang: e.holding_reply?.language ?? undefined,
  });
  return out;
}

type Clock = { t: number; cursor: number; playing: boolean };
type Act = { type: "tick"; speed: number; total: number } | { type: "play"; total: number } | { type: "pause" } |
  { type: "end"; total: number };

function clock(s: Clock, a: Act): Clock {
  switch (a.type) {
    case "tick": {
      if (!s.playing) return s;
      if (s.t < ARRIVE_MS) return { ...s, t: Math.min(ARRIVE_MS, s.t + TICK_MS * a.speed) };
      const cursor = Math.min(a.total, s.cursor + (TICK_MS * a.speed) / STEP_MS);
      return { ...s, cursor, playing: cursor < a.total };
    }
    case "play":  // from the start when finished; else carry on
      return s.t >= ARRIVE_MS && s.cursor >= a.total ? { t: 0, cursor: 0, playing: true } : { ...s, playing: true };
    case "pause":
      return { ...s, playing: false };
    case "end":
      return { t: ARRIVE_MS, cursor: a.total, playing: false };
  }
}

const REDUCE = "(prefers-reduced-motion: reduce)";
function subscribeReduce(on: () => void) {
  const q = window.matchMedia(REDUCE);
  q.addEventListener("change", on);
  return () => q.removeEventListener("change", on);
}

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReduce, () => window.matchMedia(REDUCE).matches, () => false);
}

export function NightPlayback({ business, events }: { business: string; events: NightEvent[] }) {
  const rows = useMemo(() => events.map((e) => ({ e, minute: minuteOfNight(e.at), steps: steps(e) })), [events]);
  const total = rows.reduce((n, r) => n + r.steps.length, 0);
  const reduce = usePrefersReducedMotion();
  // Opens finished: the whole night, readable without playing it.
  const [{ t, cursor, playing }, dispatch] = useReducer(clock, { t: ARRIVE_MS, cursor: total, playing: false });
  const [speed, setSpeed] = useState<1 | 4>(1);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => dispatch({ type: "tick", speed, total }), TICK_MS);
    return () => window.clearInterval(id);
  }, [playing, speed, total]);

  useEffect(() => {
    if (reduce) dispatch({ type: "end", total });
  }, [reduce, total]);

  const arriving = t < ARRIVE_MS;
  const nowMinute = (t / ARRIVE_MS) * NIGHT_MIN;
  const finished = !arriving && cursor >= total;

  // Which steps each row shows: none while messages arrive; then the night shift works through rows in order.
  const starts = rows.map((_, i) => rows.slice(0, i).reduce((n, r) => n + r.steps.length, 0));
  const shown = rows.map((r, i) => (arriving ? 0 : Math.max(0, Math.min(r.steps.length, Math.floor(cursor) - starts[i]))));
  const working = !arriving && !finished ? shown.findIndex((n, i) => n < rows[i].steps.length) : -1;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="font-serif text-[2rem] leading-none tabular-nums text-ink" aria-label="Time on the night clock">
          {arriving ? clockText(nowMinute) : "06:15"}
        </p>
        <p className="min-w-0 flex-1 basis-48 text-[0.88rem] text-ink-2" aria-live="polite">
          {arriving
            ? "Messages coming in. Pheri reads nothing yet: the night shift runs at 06:15."
            : finished
              ? "06:15: the night shift ran. Nothing goes out before 08:00, when quiet hours end."
              : "06:15: the night shift works through every message."}
          <span className="block text-[0.8rem] text-muted">Replaying a recorded run · Nepal time</span>
        </p>
        {!reduce && (
          <div className="flex w-full items-center gap-2 sm:w-auto" role="group" aria-label="Replay controls">
            <button
              onClick={() => dispatch(playing ? { type: "pause" } : { type: "play", total })}
              className="rounded-xl bg-teal px-4 py-2 text-[0.92rem] font-medium text-white hover:bg-teal-ink"
            >
              {playing ? "Pause" : finished ? "▶ Replay the night" : "▶ Play"}
            </button>
            {([1, 4] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSpeed(s)}
                aria-pressed={speed === s}
                className={`rounded-lg border px-2.5 py-1.5 text-[0.88rem] ${speed === s ? "border-teal bg-teal-soft text-teal-ink" : "border-line-2 text-ink-2 hover:bg-sunk"}`}
              >
                {s}×
              </button>
            ))}
            {!finished && (
              <button
                onClick={() => dispatch({ type: "end", total })}
                className="rounded-lg px-2 py-1.5 text-[0.88rem] text-ink-2 underline hover:text-ink"
              >
                Show all
              </button>
            )}
          </div>
        )}
      </div>
      {reduce && (
        <p className="mt-2 text-[0.85rem] text-muted">Your device asks for less motion, so the whole night is shown at once.</p>
      )}
      {arriving && (
        <div className="mt-3 h-1 overflow-hidden rounded bg-sunk" aria-hidden>
          <div className="h-full bg-teal" style={{ width: `${(t / ARRIVE_MS) * 100}%` }} />
        </div>
      )}

      <ol className="mt-4 border-l-2 border-line pl-4">
        {rows.map((r, i) => {
          if (arriving && r.minute > nowMinute) return null;
          const { e } = r;
          const last = r.steps[r.steps.length - 1];
          const done = shown[i] === r.steps.length;
          const traceable = e.outcome !== "stopped" && e.outcome !== "blocked";
          return (
            <li key={`${e.customer.key}-${i}`} className={`relative rounded-lg pb-5 ${i === working ? "bg-sunk/60" : ""}`}>
              <span
                aria-hidden
                className={`absolute top-1.5 -left-[1.42rem] h-3 w-3 rounded-full ${done ? DOT[last.tone] : "bg-line-2"}`}
              />
              <p className="text-[0.85rem] text-muted">
                {e.at ? clockNPT(e.at) : ""} ·{" "}
                <Link
                  href={traceable ? `/${business}/customers/${encodeURIComponent(e.customer.key)}/trace` : `/${business}/customers/${encodeURIComponent(e.customer.key)}`}
                  className="text-ink-2 underline decoration-line-2 underline-offset-2 hover:text-teal-ink"
                  title={traceable ? "See every turn of this decision" : "See this customer"}
                >
                  {e.customer.name}
                </Link>{" "}
                · {LANGUAGE_NAME[e.lang ?? ""] ?? e.lang}
                {e.kind === "voice_note" ? " · voice note" : ""}
              </p>
              {e.text ? (
                <p lang={e.lang ?? undefined} className="mt-0.5 font-serif text-[1.05rem] leading-snug text-ink">&ldquo;{e.text}&rdquo;</p>
              ) : (
                <p className="mt-0.5 text-[0.95rem] text-amber">{e.voice}</p>
              )}
              {shown[i] > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[0.88rem]">
                  {r.steps.slice(0, shown[i]).map((s, j) => (
                    <li key={j} className={`${TEXT[s.tone]} ${j === r.steps.length - 1 ? "font-medium" : ""}`}>
                      {s.text}
                      {s.note && (
                        <span lang={s.lang} className="mt-1 block border-l-2 border-line-2 pl-3 font-normal text-ink-2">
                          {s.note}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
