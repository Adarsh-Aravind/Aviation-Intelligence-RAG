"use client";

import {
  ArrowRight,
  BookOpen,
  Brain,
  Cpu,
  Database,
  FileSearch,
  FileText,
  Layers,
  MessageSquareText,
  Quote,
  Server,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, Skeleton, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import type { DocumentOut, HealthResponse, StatsResponse } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

function StatCard({ label, value, icon: Icon }: { label: string; value?: number; icon: typeof FileText }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-muted">
        <span className="text-xs uppercase tracking-wider">{label}</span>
        <Icon className="h-4 w-4" />
      </div>
      <div className="mt-2 font-mono text-2xl font-semibold">
        {value === undefined ? <Skeleton className="h-7 w-16" /> : value.toLocaleString()}
      </div>
    </Card>
  );
}

function StatusRow({ label, detail, ok, icon: Icon }: { label: string; detail: string; ok?: boolean; icon: typeof Cpu }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-2 text-muted">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm">{label}</p>
        <p className="truncate font-mono text-[11px] text-subtle">{detail}</p>
      </div>
      <span
        className={cn(
          "inline-flex items-center gap-1.5 text-xs",
          ok === undefined ? "text-subtle" : ok ? "text-success" : "text-danger",
        )}
      >
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            ok === undefined ? "animate-pulse bg-subtle" : ok ? "bg-success shadow-[0_0_8px] shadow-success" : "bg-danger",
          )}
        />
        {ok === undefined ? "Checking" : ok ? "Online" : "Offline"}
      </span>
    </div>
  );
}

const PIPELINE = [
  { icon: FileText, title: "Ingest", text: "PDFs are parsed page by page; running headers and page numbers are stripped." },
  { icon: Layers, title: "Chunk", text: "Section-aware chunks keep document, page range and heading metadata." },
  { icon: Cpu, title: "Embed", text: "A local ONNX model (bge-small) embeds chunks on CPU — no GPU needed." },
  { icon: FileSearch, title: "Retrieve", text: "pgvector cosine search finds the most relevant passages for each question." },
  { icon: Brain, title: "Generate", text: "Groq LLM answers using only those passages and must cite every claim." },
];

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [docs, setDocs] = useState<DocumentOut[] | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealthError(true));
    api.stats().then(setStats).catch(() => undefined);
    api
      .documents()
      .then((d) => setDocs(d.items.slice(0, 5)))
      .catch(() => setDocs([]));
  }, []);

  const apiOk = health ? true : healthError ? false : undefined;
  const readyDocs = stats?.documents_by_status.ready ?? (stats ? 0 : undefined);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-12">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-surface-2 via-surface to-bg p-6 sm:p-10">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full border border-accent/10">
          <div className="animate-radar absolute inset-0 rounded-full bg-[conic-gradient(from_0deg,transparent_0deg,rgba(56,189,248,0.18)_40deg,transparent_60deg)]" />
          <div className="absolute inset-10 rounded-full border border-accent/10" />
          <div className="absolute inset-20 rounded-full border border-accent/10" />
        </div>
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-accent">Retrieval-augmented generation</p>
        <h1 className="mt-3 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
          Answers from aviation documents — <span className="text-accent">with the page to prove it.</span>
        </h1>
        <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted sm:text-base">
          Ask about aircraft performance, weather minimums, regulations or procedures. Every answer is generated only
          from the indexed library and cites the exact document and page it came from.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/chat"
            className="inline-flex h-11 items-center gap-2 rounded-lg bg-accent-strong px-5 text-sm font-medium text-white hover:bg-accent"
          >
            <MessageSquareText className="h-4 w-4" /> Ask a question <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/documents"
            className="inline-flex h-11 items-center gap-2 rounded-lg border border-border-strong bg-surface-2 px-5 text-sm hover:bg-surface-3"
          >
            <BookOpen className="h-4 w-4" /> Browse library
          </Link>
        </div>
      </section>

      {/* Stats */}
      <section className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Documents" value={readyDocs} icon={BookOpen} />
        <StatCard label="Pages indexed" value={stats?.pages_total} icon={FileText} />
        <StatCard label="Chunks" value={stats?.chunks_total} icon={Layers} />
        <StatCard
          label="Processing"
          value={stats ? (stats.documents_by_status.queued ?? 0) + (stats.documents_by_status.processing ?? 0) : undefined}
          icon={Cpu}
        />
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-5">
        {/* System status */}
        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold">System status</h2>
          <div className="mt-2 divide-y divide-border">
            <StatusRow label="API server" detail={health ? `v${health.version} · self-hosted` : "FastAPI"} ok={apiOk} icon={Server} />
            <StatusRow
              label="Vector database"
              detail="Supabase Postgres + pgvector"
              ok={health ? health.database : healthError ? false : undefined}
              icon={Database}
            />
            <StatusRow
              label="Embedding model"
              detail={health?.embedding_model ?? "local ONNX"}
              ok={health ? health.embedder_loaded : healthError ? false : undefined}
              icon={Cpu}
            />
            <StatusRow
              label="Language model"
              detail={health ? `Groq · ${health.llm_model}` : "Groq"}
              ok={health ? health.llm_configured : healthError ? false : undefined}
              icon={Brain}
            />
          </div>
        </Card>

        {/* Recent documents */}
        <Card className="p-5 lg:col-span-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Recently added</h2>
            <Link href="/documents" className="text-xs text-accent hover:underline">
              View all
            </Link>
          </div>
          <div className="mt-3 space-y-2">
            {docs === null &&
              Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
            {docs?.length === 0 && (
              <p className="py-8 text-center text-sm text-muted">No documents yet.</p>
            )}
            {docs?.map((d) => (
              <div key={d.id} className="flex items-center gap-3 rounded-lg border border-border bg-surface-2/60 px-3 py-2.5">
                <FileText className="h-4 w-4 shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{d.title}</p>
                  <p className="font-mono text-[11px] text-subtle">
                    {d.page_count ?? "—"} pages · {formatDate(d.created_at)}
                  </p>
                </div>
                <StatusBadge status={d.status} />
              </div>
            ))}
          </div>
        </Card>
      </section>

      {/* How it works */}
      <section className="mt-6">
        <Card className="p-5">
          <h2 className="text-sm font-semibold">How answers are grounded</h2>
          <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {PIPELINE.map(({ icon: Icon, title, text }, i) => (
              <li key={title} className="rounded-lg border border-border bg-surface-2/50 p-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-subtle">0{i + 1}</span>
                  <Icon className="h-4 w-4 text-accent" />
                  <span className="text-sm font-medium">{title}</span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-muted">{text}</p>
              </li>
            ))}
          </ol>
          <p className="mt-4 flex items-start gap-2 text-xs text-muted">
            <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
            If no passage is relevant enough, the system says the sources don&apos;t cover the question instead of
            guessing — and the language model is never asked.
          </p>
        </Card>
      </section>
    </div>
  );
}
