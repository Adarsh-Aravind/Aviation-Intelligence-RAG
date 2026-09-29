"use client";

import { CloudOff, DatabaseZap } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

type State = "unknown" | "online" | "offline" | "degraded";

/**
 * The backend runs on a home server that can lose power or Wi-Fi. Check its health
 * periodically and explain the situation instead of letting requests fail mysteriously.
 */
export function ServerStatusBanner() {
  const [state, setState] = useState<State>("unknown");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const check = async () => {
      let next: State;
      try {
        const h = await api.health();
        next = h.database ? "online" : "degraded";
      } catch {
        next = "offline";
      }
      if (cancelled) return;
      setState(next);
      // Poll faster while something is wrong so the banner clears soon after recovery.
      timer = setTimeout(check, next === "online" ? 60_000 : 15_000);
    };

    void check();
    const onFocus = () => {
      clearTimeout(timer);
      void check();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  if (state === "offline") {
    return (
      <div role="status" className="flex shrink-0 items-start gap-3 border-b border-warning/30 bg-warning/10 px-4 py-2.5 text-sm sm:px-6">
        <CloudOff className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <p className="text-warning">
          <span className="font-medium">The AI server is temporarily offline.</span>{" "}
          <span className="text-warning/80">
            It&apos;s self-hosted on a home server and may be recovering from a power or internet outage. This page
            reconnects automatically.
          </span>
        </p>
      </div>
    );
  }
  if (state === "degraded") {
    return (
      <div role="status" className="flex shrink-0 items-start gap-3 border-b border-warning/30 bg-warning/10 px-4 py-2.5 text-sm sm:px-6">
        <DatabaseZap className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <p className="text-warning">
          <span className="font-medium">Reconnecting to the document database…</span>{" "}
          <span className="text-warning/80">Answers may be unavailable for a moment.</span>
        </p>
      </div>
    );
  }
  return null;
}
