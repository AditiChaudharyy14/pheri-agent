"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BUSINESSES, type Business } from "@/lib/api";

const LINKS = [
  { href: "", label: "Next steps" },
  { href: "/journey", label: "Journey" },
  { href: "/rules", label: "Rules" },
  { href: "/safety", label: "Safety" },
  { href: "/proof", label: "Proof" },
  { href: "/spend", label: "Spend" },
];

export function Nav({ business }: { business: Business }) {
  const path = usePathname();
  const base = `/${business}`;
  return (
    <nav className="flex items-center gap-1" aria-label="Sections">
      {LINKS.map((l) => {
        const href = base + l.href;
        const active = l.href === "" ? path === base || path.startsWith(`${base}/customers`) : path.startsWith(href);
        return (
          <Link
            key={l.label}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`rounded-full px-4 py-2 text-[0.95rem] transition-colors ${
              active ? "bg-teal-soft text-teal-ink font-medium" : "text-ink-2 hover:bg-sunk"
            }`}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function BusinessSwitch({ business }: { business: Business }) {
  const path = usePathname();
  // Same section in the other business; a customer page belongs to one business, so go to its home.
  const rest = path.replace(`/${business}`, "");
  const target = (b: Business) => `/${b}${rest.startsWith("/customers") ? "" : rest}`;
  return (
    <div className="flex rounded-full border border-line bg-surface p-1" role="group" aria-label="Business">
      {(Object.keys(BUSINESSES) as Business[]).map((b) => (
        <Link
          key={b}
          href={target(b)}
          aria-current={b === business ? "true" : undefined}
          className={`rounded-full px-4 py-1.5 text-[0.95rem] ${
            b === business ? "bg-ink text-paper font-medium" : "text-ink-2 hover:bg-sunk"
          }`}
        >
          {BUSINESSES[b]}
        </Link>
      ))}
    </div>
  );
}
