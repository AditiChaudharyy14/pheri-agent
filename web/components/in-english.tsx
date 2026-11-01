"use client";

import { createContext, type ReactNode, useContext } from "react";

/** In English, for readers who don't read the customer's language: a translation of the text just above it, made once
 * by Muse Spark 1.3 (recorded, replayed) and checked in code so it adds no number or claim the original lacks
 * (api/pheri/translate.py). It is for the reader only: never sent, and nothing reads it. No translation, no line. */

const English = createContext<Record<string, string>>({});

export function EnglishProvider({ map, children }: { map: Record<string, string>; children: ReactNode }) {
  return <English.Provider value={map}>{children}</English.Provider>;
}

export function InEnglish({ text, className = "" }: { text: string | null | undefined; className?: string }) {
  const map = useContext(English);
  const en = text ? map[text.trim()] ?? map[text] : undefined;
  if (!en) return null;
  return (
    <span lang="en" className={`mt-1 block font-sans text-[0.84rem] leading-snug font-normal text-muted not-italic ${className}`}>
      <span className="text-[0.78rem]">In English (a translation for readers, never sent):</span> {en}
    </span>
  );
}
