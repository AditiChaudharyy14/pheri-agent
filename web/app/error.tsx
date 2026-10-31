"use client";

/** When Pheri's server can't be reached or answers with an error: say so plainly, and offer to try again. */
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div role="alert" className="mx-auto max-w-[40rem] rounded-2xl border border-l-4 border-line border-l-vermilion bg-surface p-6">
      <h1 className="text-[1.6rem] font-medium">Pheri&rsquo;s server didn&rsquo;t answer.</h1>
      <p className="mt-2 text-ink-2">
        Nothing was sent to any customer: messages only go out after the server checks them. Try again in a moment.
      </p>
      <p className="mt-2 text-[0.85rem] text-muted">{error.digest ? `Reference ${error.digest}` : error.message}</p>
      <button onClick={reset} className="mt-4 rounded-xl bg-teal px-5 py-2.5 font-medium text-white hover:bg-teal-ink">
        Try again
      </button>
    </div>
  );
}
