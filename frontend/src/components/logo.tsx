import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("h-8 w-8", className)} aria-hidden>
      <defs>
        <linearGradient id="lm" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#38bdf8" />
          <stop offset="1" stopColor="#0369a1" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#lm)" />
      <circle cx="16" cy="16" r="9.5" fill="none" stroke="white" strokeOpacity=".35" strokeWidth="1" />
      <path
        d="M16 6.5l1.6 7.2 7.4 3.1-7.4 1.2-.9 6.2 2.3 1.4v.9L16 25.6l-3 .9v-.9l2.3-1.4-.9-6.2-7.4-1.2 7.4-3.1z"
        fill="white"
      />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark className={compact ? "h-7 w-7" : "h-8 w-8"} />
      <span className="leading-tight">
        <span className="block text-sm font-semibold tracking-tight">Aviation Intelligence</span>
        {!compact && (
          <span className="block font-mono text-[10px] uppercase tracking-[0.18em] text-accent">
            Grounded RAG
          </span>
        )}
      </span>
    </span>
  );
}
