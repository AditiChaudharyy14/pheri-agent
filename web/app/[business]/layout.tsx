import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BusinessSwitch, Nav } from "@/components/nav";
import { api, isBusiness } from "@/lib/api";

export function generateStaticParams() {
  return [{ business: "brightdesk" }, { business: "kettle" }];
}

async function ModePill() {
  const h = await api<{ mode: string }>("/health");
  return h.mode === "mock" ? (
    <span className="rounded-full border border-line px-3 py-1 text-[0.8rem] text-muted" title="No model calls, no spend">
      Mock mode · synthetic data
    </span>
  ) : (
    <span className="rounded-full bg-amber-soft px-3 py-1 text-[0.8rem] text-amber">Live models</span>
  );
}

function Frame({ business, right, nav }: { business?: string; right?: React.ReactNode; nav?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-paper/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1240px] items-center justify-between gap-6 px-10 pt-4 pb-3">
        <Link href={business ? `/${business}` : "/"} className="flex items-baseline gap-3">
          <span className="font-serif text-[1.7rem] font-semibold text-ink">Pheri</span>
          <span className="hidden text-[0.85rem] text-muted xl:inline">the next step for every customer, inside your rules</span>
        </Link>
        {right}
      </div>
      <div className="mx-auto h-[3.25rem] max-w-[1240px] px-9 pb-3">{nav}</div>
    </header>
  );
}

// Reading the route's business is URL data: it streams behind Suspense, with the plain frame as the fallback.
async function Header({ params }: { params: LayoutProps<"/[business]">["params"] }) {
  const { business } = await params;
  if (!isBusiness(business)) notFound();
  return (
    <Frame
      business={business}
      right={
        <div className="flex items-center gap-4">
          <Suspense fallback={null}>
            <ModePill />
          </Suspense>
          <BusinessSwitch business={business} />
        </div>
      }
      nav={<Nav business={business} />}
    />
  );
}

export default function BusinessLayout({ children, params }: LayoutProps<"/[business]">) {
  return (
    <div className="min-h-screen">
      <Suspense fallback={<Frame />}>
        <Header params={params} />
      </Suspense>
      <main className="mx-auto max-w-[1240px] px-10 py-10">{children}</main>
    </div>
  );
}
