"use client";

import {
  AlertTriangle,
  ArrowUp,
  BookMarked,
  CircleCheck,
  Info,
  RotateCcw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Answer } from "@/components/chat/answer";
import { SourcesPanel } from "@/components/chat/sources-panel";
import { LogoMark } from "@/components/logo";
import { Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";
import { cn, formatMs } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  error?: string;
  question?: string; // for retry
  pending?: boolean;
}

const STORAGE_KEY = "air-chat-v1";
const SUGGESTIONS = [
  "How does high density altitude affect takeoff performance?",
  "What are the steps to recover from a stall?",
  "What are the basic VFR weather minimums?",
  "Why must the center of gravity stay within limits?",
];

const uid = () => Math.random().toString(36).slice(2, 10);

function loadHistory(): Message[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Message[]).filter((m) => !m.pending) : [];
  } catch {
    return [];
  }
}

function GroundingBadge({ r }: { r: ChatResponse }) {
  if (r.status === "insufficient_context") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-[11px] text-warning">
        <Info className="h-3 w-3" /> Not covered by the library
      </span>
    );
  }
  if (!r.grounded) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-danger/30 bg-danger/10 px-2 py-0.5 text-[11px] text-danger">
        <AlertTriangle className="h-3 w-3" /> No citations — verify independently
      </span>
    );
  }
  const docs = new Set(r.citations.map((c) => c.document_id)).size;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-[11px] text-success">
      <CircleCheck className="h-3 w-3" /> Grounded in {r.citations.length} passage{r.citations.length > 1 ? "s" : ""} from{" "}
      {docs} document{docs > 1 ? "s" : ""}
    </span>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeMsgId, setActiveMsgId] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const history = loadHistory();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate from sessionStorage after mount
    setMessages(history);
    const lastAnswer = [...history].reverse().find((m) => m.response);
    if (lastAnswer) setActiveMsgId(lastAnswer.id);
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages.filter((m) => !m.pending).slice(-40)));
    } catch {
      /* storage full or unavailable — history is a convenience only */
    }
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (q.length < 2 || busy) return;
      setBusy(true);
      setInput("");
      const userMsg: Message = { id: uid(), role: "user", content: q };
      const pendingId = uid();
      setMessages((m) => [...m, userMsg, { id: pendingId, role: "assistant", content: "", pending: true }]);
      try {
        const response = await api.ask(q);
        setMessages((m) =>
          m.map((msg) => (msg.id === pendingId ? { id: pendingId, role: "assistant", content: response.answer, response } : msg)),
        );
        setActiveMsgId(pendingId);
        setActiveSource(response.citations[0]?.n ?? null);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Something went wrong.";
        setMessages((m) =>
          m.map((msg) => (msg.id === pendingId ? { id: pendingId, role: "assistant", content: "", error: message, question: q } : msg)),
        );
      } finally {
        setBusy(false);
        inputRef.current?.focus();
      }
    },
    [busy],
  );

  const retry = (msg: Message) => {
    if (!msg.question) return;
    setMessages((m) => {
      const idx = m.findIndex((x) => x.id === msg.id);
      return m.slice(0, Math.max(0, idx - 1)); // drop the failed pair; ask() re-adds it
    });
    void ask(msg.question);
  };

  const activeResponse = messages.find((m) => m.id === activeMsgId)?.response ?? null;
  const selectSource = (msgId: string, n: number) => {
    setActiveMsgId(msgId);
    setActiveSource(n);
    if (window.matchMedia("(max-width: 1023px)").matches) setSheetOpen(true);
  };

  return (
    <div className="flex h-full">
      {/* Conversation column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-border px-4 py-3 sm:px-6">
          <div>
            <h1 className="text-sm font-semibold">Ask the Library</h1>
            <p className="text-xs text-muted">Answers come only from indexed aviation documents.</p>
          </div>
          {messages.length > 0 && (
            <button
              onClick={() => {
                setMessages([]);
                setActiveMsgId(null);
                setActiveSource(null);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted hover:bg-surface-2 hover:text-text"
            >
              <Trash2 className="h-3.5 w-3.5" /> Clear
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.length === 0 && (
              <div className="pt-6 text-center sm:pt-12">
                <LogoMark className="mx-auto h-12 w-12" />
                <h2 className="mt-4 text-xl font-semibold">What would you like to know?</h2>
                <p className="mx-auto mt-2 max-w-md text-sm text-muted">
                  Ask about procedures, performance, weather or regulations. If the library doesn&apos;t cover it,
                  you&apos;ll be told — no guessing.
                </p>
                <div className="mx-auto mt-8 grid max-w-2xl gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => void ask(s)}
                      className="rounded-xl border border-border bg-surface/80 px-4 py-3 text-left text-sm text-muted transition-colors hover:border-accent/40 hover:text-text"
                    >
                      <Sparkles className="mb-1.5 h-3.5 w-3.5 text-accent" />
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent-strong/90 px-4 py-2.5 text-sm text-white">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={m.id} className="flex gap-3">
                  <LogoMark className="h-7 w-7 shrink-0" />
                  <div className="min-w-0 flex-1">
                    {m.pending && (
                      <div className="space-y-2 pt-1">
                        <p className="text-xs text-muted">Searching the library and composing a grounded answer…</p>
                        <Skeleton className="h-3.5 w-11/12" />
                        <Skeleton className="h-3.5 w-9/12" />
                        <Skeleton className="h-3.5 w-10/12" />
                      </div>
                    )}
                    {m.error && (
                      <div className="rounded-xl border border-danger/30 bg-danger/10 p-3 text-sm">
                        <p className="flex items-center gap-2 text-danger">
                          <AlertTriangle className="h-4 w-4" /> {m.error}
                        </p>
                        {m.question && (
                          <button
                            onClick={() => retry(m)}
                            className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted hover:text-text"
                          >
                            <RotateCcw className="h-3.5 w-3.5" /> Retry
                          </button>
                        )}
                      </div>
                    )}
                    {m.response && (
                      <div
                        className={cn(
                          "rounded-2xl rounded-tl-md border bg-surface/80 px-4 py-3",
                          activeMsgId === m.id ? "border-border-strong" : "border-border",
                        )}
                      >
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          <GroundingBadge r={m.response} />
                        </div>
                        <Answer
                          text={m.content}
                          activeSource={activeMsgId === m.id ? activeSource : null}
                          onCite={(n) => selectSource(m.id, n)}
                        />
                        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2">
                          <span className="font-mono text-[10px] text-subtle">
                            retrieval {formatMs(m.response.timings.embedding_ms + m.response.timings.retrieval_ms)}
                            {m.response.model && ` · ${m.response.model} ${formatMs(m.response.timings.llm_ms)}`}
                          </span>
                          {(m.response.citations.length > 0 || m.response.retrieved.length > 0) && (
                            <button
                              onClick={() => {
                                setActiveMsgId(m.id);
                                setActiveSource(m.response?.citations[0]?.n ?? null);
                                if (window.matchMedia("(max-width: 1023px)").matches) setSheetOpen(true);
                              }}
                              className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
                            >
                              <BookMarked className="h-3 w-3" /> View sources
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-border bg-bg/80 px-4 py-3 backdrop-blur sm:px-6">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(input);
            }}
            className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-border-strong bg-surface-2 p-2 focus-within:border-accent/50"
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask(input);
                }
              }}
              rows={1}
              maxLength={1000}
              placeholder="Ask about aviation procedures, performance, regulations…"
              className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm placeholder:text-subtle focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || input.trim().length < 2}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-strong text-white transition-colors hover:bg-accent disabled:opacity-40"
              aria-label="Send"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          </form>
          <p className="mx-auto mt-2 max-w-3xl text-center text-[10px] text-subtle">
            Answers are generated from retrieved passages only and may still contain errors. Not for operational use.
          </p>
        </div>
      </div>

      {/* Desktop sources panel */}
      <aside className="hidden w-[400px] shrink-0 overflow-y-auto border-l border-border bg-surface/40 p-4 lg:block">
        <h2 className="mb-4 text-sm font-semibold">Sources</h2>
        <SourcesPanel
          response={activeResponse}
          activeSource={activeSource}
          onSelect={(n) => setActiveSource(n)}
        />
      </aside>

      {/* Mobile sources sheet */}
      {sheetOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setSheetOpen(false)} />
          <div className="absolute inset-x-0 bottom-0 max-h-[80dvh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-4">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Sources</h2>
              <button onClick={() => setSheetOpen(false)} aria-label="Close sources" className="text-muted">
                <X className="h-5 w-5" />
              </button>
            </div>
            <SourcesPanel response={activeResponse} activeSource={activeSource} onSelect={(n) => setActiveSource(n)} />
          </div>
        </div>
      )}
    </div>
  );
}
