"use client";

import { AlertCircle, BookOpen, ExternalLink, FileText, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { UploadDialog } from "@/components/documents/upload-dialog";
import { useSession } from "@/components/session-provider";
import { Button, Card, EmptyState, Input, Modal, Skeleton, StatusBadge } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { openDocumentAtPage } from "@/lib/open-document";
import type { DocumentOut } from "@/lib/types";
import { formatBytes, formatDate } from "@/lib/utils";

export default function DocumentsPage() {
  const { admin } = useSession();
  const [docs, setDocs] = useState<DocumentOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [toDelete, setToDelete] = useState<DocumentOut | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.documents();
      setDocs(res.items);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load documents.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  // Poll while anything is still being processed.
  const inFlight = docs?.some((d) => d.status === "queued" || d.status === "processing") ?? false;
  useEffect(() => {
    if (!inFlight) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [inFlight, load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!docs || !q) return docs;
    return docs.filter((d) => `${d.title} ${d.description ?? ""} ${d.original_filename}`.toLowerCase().includes(q));
  }, [docs, query]);

  const reprocess = async (d: DocumentOut) => {
    try {
      await api.reprocess(d.id);
      toast.success("Re-processing started");
      void load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not reprocess");
    }
  };

  const confirmDelete = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api.deleteDocument(toDelete.id);
      toast.success(`Deleted “${toDelete.title}”`);
      setToDelete(null);
      void load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Document Library</h1>
          <p className="mt-1 text-sm text-muted">
            The aviation documents every answer is grounded in.
            {!admin && " Sign in as admin to add or remove documents."}
          </p>
        </div>
        {admin && (
          <Button onClick={() => setUploadOpen(true)}>
            <Plus className="h-4 w-4" /> Upload PDF
          </Button>
        )}
      </div>

      <div className="relative mt-6 max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" />
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter documents…" className="pl-9" />
      </div>

      <div className="mt-4">
        {error && (
          <Card className="flex items-center justify-between gap-3 border-danger/30 p-4 text-sm">
            <span className="flex items-center gap-2 text-danger">
              <AlertCircle className="h-4 w-4" /> {error}
            </span>
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              Retry
            </Button>
          </Card>
        )}
        {!error && docs === null && (
          <div className="grid gap-3 md:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-36 w-full rounded-xl" />
            ))}
          </div>
        )}
        {!error && docs?.length === 0 && (
          <EmptyState icon={<BookOpen className="h-5 w-5" />} title="The library is empty">
            {admin ? "Upload an aviation PDF to get started." : "Documents will appear here once an admin uploads them."}
          </EmptyState>
        )}
        {filtered && filtered.length > 0 && (
          <div className="grid gap-3 md:grid-cols-2">
            {filtered.map((d) => (
              <Card key={d.id} className="flex flex-col p-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <h2 className="line-clamp-2 text-sm font-medium">{d.title}</h2>
                      <StatusBadge status={d.status} />
                    </div>
                    <p className="mt-0.5 truncate font-mono text-[11px] text-subtle">{d.original_filename}</p>
                  </div>
                </div>
                {d.description && <p className="mt-3 line-clamp-2 text-xs text-muted">{d.description}</p>}
                {d.status === "failed" && d.error_message && (
                  <p className="mt-3 rounded-md border border-danger/25 bg-danger/10 px-2.5 py-1.5 text-xs text-danger">
                    {d.error_message}
                  </p>
                )}
                <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4">
                  <p className="font-mono text-[11px] text-muted">
                    {d.page_count ?? "—"} pages · {d.chunk_count} chunks · {formatBytes(d.file_size)} · {formatDate(d.created_at)}
                  </p>
                  <div className="flex items-center gap-1">
                    {d.status === "ready" && (
                      <Button variant="ghost" size="sm" onClick={() => void openDocumentAtPage(d.id, 1)}>
                        <ExternalLink className="h-3.5 w-3.5" /> Open
                      </Button>
                    )}
                    {admin && (d.status === "failed" || d.status === "ready") && (
                      <Button variant="ghost" size="sm" onClick={() => void reprocess(d)} aria-label="Reprocess">
                        <RefreshCw className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    {admin && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setToDelete(d)}
                        aria-label="Delete"
                        className="hover:text-danger"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
        {filtered && docs && docs.length > 0 && filtered.length === 0 && (
          <p className="py-10 text-center text-sm text-muted">No documents match “{query}”.</p>
        )}
      </div>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={() => void load()} />

      <Modal open={toDelete !== null} onClose={() => !deleting && setToDelete(null)} title="Delete document?">
        <p className="text-sm text-muted">
          “{toDelete?.title}” and all of its indexed passages will be permanently removed. Answers will no longer cite it.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setToDelete(null)} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="danger" onClick={confirmDelete} loading={deleting}>
            Delete
          </Button>
        </div>
      </Modal>
    </div>
  );
}
