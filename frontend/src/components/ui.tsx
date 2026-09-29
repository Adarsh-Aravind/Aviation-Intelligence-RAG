// Small design-system primitives (Tailwind only).
import { Loader2 } from "lucide-react";
import { forwardRef } from "react";

import type { DocumentStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean; size?: "sm" | "md" }
>(function Button({ className, variant = "primary", size = "md", loading, disabled, children, ...props }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-accent-strong text-white hover:bg-accent",
        variant === "secondary" && "border border-border-strong bg-surface-2 text-text hover:bg-surface-3",
        variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-text",
        variant === "danger" && "bg-danger/90 text-white hover:bg-danger",
        className,
      )}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
});

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-xl border border-border bg-surface/80 backdrop-blur", className)} {...props} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface-3/70", className)} />;
}

const STATUS_STYLE: Record<DocumentStatus, { label: string; className: string; dot: string }> = {
  ready: { label: "Ready", className: "text-success bg-success/10 border-success/25", dot: "bg-success" },
  processing: {
    label: "Processing",
    className: "text-accent bg-accent/10 border-accent/25",
    dot: "bg-accent animate-pulse",
  },
  queued: { label: "Queued", className: "text-warning bg-warning/10 border-warning/25", dot: "bg-warning" },
  failed: { label: "Failed", className: "text-danger bg-danger/10 border-danger/25", dot: "bg-danger" },
  awaiting_upload: {
    label: "Uploading",
    className: "text-muted bg-surface-3 border-border",
    dot: "bg-muted animate-pulse",
  },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const s = STATUS_STYLE[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        s.className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "h-10 w-full rounded-lg border border-border bg-surface-2 px-3 text-sm text-text placeholder:text-subtle",
        "focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20",
        props.className,
      )}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cn(
        "w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-text placeholder:text-subtle",
        "focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20",
        props.className,
      )}
    />
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-t-2xl border border-border bg-surface p-5 shadow-2xl sm:rounded-2xl">
        <h2 className="mb-4 text-base font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-14 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft text-accent">{icon}</div>
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-muted">{children}</div>}
    </div>
  );
}
