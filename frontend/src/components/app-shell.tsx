"use client";

import { BookOpen, LayoutDashboard, LogIn, LogOut, Menu, MessageSquareText, Shield, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Logo } from "@/components/logo";
import { ServerStatusBanner } from "@/components/server-status-banner";
import { useSession } from "@/components/session-provider";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/chat", label: "Ask the Library", icon: MessageSquareText },
  { href: "/documents", label: "Document Library", icon: BookOpen },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              active ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-text",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function AdminControl() {
  const { admin, logout } = useSession();
  if (admin) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-border bg-surface-2 px-3 py-2">
        <span className="flex items-center gap-2 text-xs text-success">
          <Shield className="h-3.5 w-3.5" /> Admin mode
        </span>
        <button
          onClick={async () => {
            await logout();
            toast.success("Signed out");
          }}
          className="text-muted hover:text-text"
          aria-label="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    );
  }
  return (
    <Link
      href="/login"
      className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-subtle hover:bg-surface-2 hover:text-text"
    >
      <LogIn className="h-3.5 w-3.5" /> Admin sign-in
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative flex h-dvh overflow-hidden">
      <div className="bg-grid pointer-events-none fixed inset-0 -z-10" />

      {/* Desktop sidebar */}
      <aside className="hidden h-dvh w-64 shrink-0 flex-col border-r border-border bg-surface/60 p-4 backdrop-blur lg:flex">
        <Link href="/" className="mb-8 px-2">
          <Logo />
        </Link>
        <NavLinks />
        <div className="mt-auto space-y-3">
          <AdminControl />
          <p className="px-2 text-[11px] leading-relaxed text-subtle">
            For study and reference only. Not for operational flight use — always consult current official
            publications.
          </p>
        </div>
      </aside>

      {/* Mobile top bar + drawer */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="z-30 flex h-14 shrink-0 items-center justify-between border-b border-border bg-bg/80 px-4 backdrop-blur lg:hidden">
          <Link href="/">
            <Logo compact />
          </Link>
          <button onClick={() => setOpen(true)} aria-label="Open menu" className="text-muted">
            <Menu className="h-5 w-5" />
          </button>
        </header>
        {open && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
            <div className="absolute right-0 top-0 flex h-full w-72 flex-col border-l border-border bg-surface p-4">
              <div className="mb-6 flex items-center justify-between">
                <Logo compact />
                <button onClick={() => setOpen(false)} aria-label="Close menu" className="text-muted">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <NavLinks onNavigate={() => setOpen(false)} />
              <div className="mt-auto">
                <AdminControl />
              </div>
            </div>
          </div>
        )}
        <ServerStatusBanner />
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
