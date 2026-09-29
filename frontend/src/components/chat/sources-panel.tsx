"use client";

import { BookMarked, ExternalLink, FileText } from "lucide-react";
import { useEffect, useRef } from "react";

import { openDocumentAtPage } from "@/lib/open-document";
import type { ChatResponse, SourceChunk } from "@/lib/types";
import { cn, pageLabel } from "@/lib/utils";

function RelevanceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  return (
    <div className="flex items-center gap-2" title={`Cosine similarity ${score.toFixed(3)}`}>
      <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[10px] text-subtle">{score.toFixed(2)}</span>
    </div>
  );
}

function SourceCard({
  source,
  cited,
  active,
  onSelect,
}: {
  source: SourceChunk;
  cited: boolean;
  active: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [active]);

  return (
    <div
      ref={ref}
      onClick={onSelect}
      className={cn(
        "cursor-pointer rounded-xl border p-3 transition-colors",
        active ? "border-accent/60 bg-accent-soft glow" : "border-border bg-surface-2/60 hover:border-border-strong",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span
          className={cn(
            "mt-0.5 flex h-5 min-w-5 items-center justify-center rounded-md px-1 font-mono text-[10px] font-semibold",
            cited ? "bg-accent text-bg" : "bg-surface-3 text-muted",
          )}
        >
          {source.n}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={source.document_title}>
            {source.document_title}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-[11px] text-muted">
            <span>{pageLabel(source.page_start, source.page_end)}</span>
            {source.section && <span className="truncate text-subtle">§ {source.section}</span>}
          </p>
        </div>
      </div>
      <p
        className={cn(
          "mt-2.5 whitespace-pre-line border-l-2 pl-3 text-xs leading-relaxed text-muted",
          active ? "border-accent" : "border-border line-clamp-4",
        )}
      >
        {source.excerpt}
      </p>
      <div className="mt-3 flex items-center justify-between">
        <RelevanceBar score={source.score} />
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            void openDocumentAtPage(source.document_id, source.page_start);
          }}
          className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
        >
          Open PDF at p. {source.page_start} <ExternalLink className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

export function SourcesPanel({
  response,
  activeSource,
  onSelect,
}: {
  response: ChatResponse | null;
  activeSource: number | null;
  onSelect: (n: number) => void;
}) {
  if (!response) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-6 text-center">
        <BookMarked className="h-8 w-8 text-subtle" />
        <p className="mt-3 text-sm font-medium">Sources appear here</p>
        <p className="mt-1 text-xs text-muted">
          Each answer lists the exact passages it was built from, with document titles and page numbers.
        </p>
      </div>
    );
  }
  const insufficient = response.status === "insufficient_context";
  return (
    <div className="space-y-5">
      {response.citations.length > 0 && (
        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted">
            <FileText className="h-3.5 w-3.5" /> Cited sources ({response.citations.length})
          </h3>
          <div className="space-y-2">
            {response.citations.map((s) => (
              <SourceCard key={s.chunk_id} source={s} cited active={activeSource === s.n} onSelect={() => onSelect(s.n)} />
            ))}
          </div>
        </section>
      )}
      {response.retrieved.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">
            {insufficient ? "Closest passages found" : "Also retrieved (not cited)"}
          </h3>
          {insufficient && (
            <p className="mb-2 text-[11px] text-subtle">
              These were the nearest matches, but none was relevant enough to answer from.
            </p>
          )}
          <div className="space-y-2">
            {response.retrieved.map((s) => (
              <SourceCard
                key={s.chunk_id}
                source={s}
                cited={false}
                active={!insufficient && activeSource === s.n}
                onSelect={() => onSelect(s.n)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
