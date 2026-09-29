"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/** Turn "[1]" / "[1][2]" citations into links we can render as chips. */
function linkCitations(text: string): string {
  return text.replace(/\[(\d{1,2})\](?!\()/g, "[$1](#cite-$1)");
}

export function Answer({
  text,
  activeSource,
  onCite,
}: {
  text: string;
  activeSource: number | null;
  onCite: (n: number) => void;
}) {
  return (
    <div className="prose-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const m = href?.match(/^#cite-(\d+)$/);
            if (m) {
              const n = Number(m[1]);
              return (
                <button
                  type="button"
                  onClick={() => onCite(n)}
                  className={cn(
                    "mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-md px-1 align-middle font-mono text-[10px] font-semibold transition-colors",
                    activeSource === n
                      ? "bg-accent text-bg"
                      : "bg-accent-soft text-accent ring-1 ring-accent/30 hover:bg-accent/25",
                  )}
                  aria-label={`Show source ${n}`}
                >
                  {n}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-accent underline">
                {children}
              </a>
            );
          },
        }}
      >
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
}
