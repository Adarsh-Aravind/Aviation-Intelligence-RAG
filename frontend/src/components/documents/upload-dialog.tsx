"use client";

import { FileUp, FileText, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button, Input, Modal, Textarea } from "@/components/ui";
import { ApiError, api, uploadToSignedUrl } from "@/lib/api";
import { cn, formatBytes, sha256Hex } from "@/lib/utils";

const MAX_MB = 25;

type Stage = "idle" | "hashing" | "preparing" | "uploading" | "finalizing";
const STAGE_LABEL: Record<Stage, string> = {
  idle: "Upload",
  hashing: "Checking file…",
  preparing: "Preparing…",
  uploading: "Uploading…",
  finalizing: "Queuing for processing…",
};

function titleFromName(name: string) {
  return name.replace(/\.pdf$/i, "").replace(/[_-]+/g, " ").trim();
}

export function UploadDialog({ open, onClose, onUploaded }: { open: boolean; onClose: () => void; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setFile(null);
    setTitle("");
    setDescription("");
    setStage("idle");
    setProgress(0);
  };

  const pick = (f: File | undefined) => {
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Only PDF files are supported.");
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      toast.error(`File is larger than ${MAX_MB} MB.`);
      return;
    }
    setFile(f);
    if (!title) setTitle(titleFromName(f.name));
  };

  const submit = async () => {
    if (!file) return;
    try {
      setStage("hashing");
      const sha256 = await sha256Hex(file);
      setStage("preparing");
      const { document, upload_url } = await api.initUpload({
        filename: file.name,
        title: title.trim() || undefined,
        description: description.trim() || undefined,
        file_size: file.size,
        content_type: "application/pdf",
        sha256,
      });
      setStage("uploading");
      await uploadToSignedUrl(upload_url, file, setProgress);
      setStage("finalizing");
      await api.completeUpload(document.id);
      toast.success("Upload complete — processing has started.");
      reset();
      onUploaded();
      onClose();
    } catch (err) {
      setStage("idle");
      toast.error(err instanceof ApiError ? err.message : "Upload failed.");
    }
  };

  const busy = stage !== "idle";

  return (
    <Modal
      open={open}
      onClose={() => {
        if (!busy) {
          reset();
          onClose();
        }
      }}
      title="Upload aviation document"
    >
      {!file ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pick(e.dataTransfer.files[0]);
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
            dragging ? "border-accent bg-accent-soft" : "border-border hover:border-border-strong",
          )}
        >
          <FileUp className="h-8 w-8 text-accent" />
          <p className="mt-3 text-sm font-medium">Drop a PDF here or click to browse</p>
          <p className="mt-1 text-xs text-muted">Text-based PDFs up to {MAX_MB} MB · scanned documents are not supported</p>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-2 px-3 py-2.5">
            <FileText className="h-5 w-5 shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm">{file.name}</p>
              <p className="font-mono text-[11px] text-subtle">{formatBytes(file.size)}</p>
            </div>
            {!busy && (
              <button onClick={() => setFile(null)} className="text-muted hover:text-text" aria-label="Remove file">
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <label className="block">
            <span className="mb-1 block text-xs text-muted">Title</span>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} disabled={busy} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-muted">Description (optional)</span>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              rows={3}
              disabled={busy}
              placeholder="e.g. FAA Pilot's Handbook of Aeronautical Knowledge, 2023 edition"
            />
          </label>
          {stage === "uploading" && (
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
              <div className="h-full bg-accent transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
          )}
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Button
          variant="ghost"
          onClick={() => {
            reset();
            onClose();
          }}
          disabled={busy}
        >
          Cancel
        </Button>
        <Button onClick={submit} disabled={!file} loading={busy}>
          {STAGE_LABEL[stage]}
        </Button>
      </div>
    </Modal>
  );
}
