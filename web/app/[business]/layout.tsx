import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BusinessSwitch, Nav } from "@/components/nav";
import { ResetDemo } from "@/components/reset-demo";
import { api, isBusiness } from "@/lib/api";

export function generateStaticParams() {
  return [{ business: "birgunj" }, { business: "brightdesk" }];
}

async function ModePill() {
  let h: { mode: string; public_demo: boolean };
  try {
    h = await api<{ mode: string; public_demo: boolean }>("/health");
  } catch {
    return null; // the page itself says the server didn't answer (error.tsx); the header stays usable
  }
  if (h.mode === "replay") {
    return (
      <>
        <ResetDemo publicDemo={h.public_demo} />
        <span
          className="rounded-full bg-teal-soft px-3 py-1 text-[0.8rem] text-teal-ink"
          title="The model's replies were recorded in a live run and are replayed here; code runs every check again. No model calls, no spend."
        >
          Recorded from a live run · synthetic data
        </span>
      </>
    );
  }
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
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 pt-3 pb-2 lg:px-10 lg:pt-4 lg:pb-3">
        <Link href={business ? `/${business}` : "/"} className="flex items-baseline gap-3">
          <span className="font-serif text-[1.7rem] font-semibold text-ink">Pheri</span>
          <span className="hidden text-[0.85rem] text-muted xl:inline">the next step for every customer, inside your rules</span>
        </Link>
        {right}
      </div>
      <div className="mx-auto max-w-[1240px] px-3 pb-2 lg:px-9 lg:pb-3">{nav}</div>
    </header>
  );
}

// Spend proves the build stayed inside the free credits; it is evidence, not a section, so it lives down here.
async function Footer({ params }: { params: LayoutProps<"/[business]">["params"] }) {
  const { business } = await params;
  if (!isBusiness(business)) return null;
  return (
    <footer className="mx-auto max-w-[1240px] border-t border-line px-4 py-6 text-[0.88rem] text-muted lg:px-10">
      <Link href={`/${business}/spend`} className="hover:text-teal-ink">
        Built on free credits: what every model call cost →
      </Link>
    </footer>
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
        <div className="flex flex-wrap items-center gap-2 lg:gap-4">
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
      <main className="mx-auto max-w-[1240px] px-4 py-6 lg:px-10 lg:py-10">{children}</main>
      <Suspense fallback={null}>
        <Footer params={params} />
      </Suspense>
    </div>
  );
}
