// Mirrors backend/app/models/schemas.py — keep in sync.

export type DocumentStatus = "awaiting_upload" | "queued" | "processing" | "ready" | "failed";

export interface DocumentOut {
  id: string;
  title: string;
  description: string | null;
  original_filename: string;
  file_type: string;
  file_size: number;
  page_count: number | null;
  chunk_count: number;
  status: DocumentStatus;
  error_message: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface DocumentList {
  items: DocumentOut[];
  total: number;
}

export interface UploadInitRequest {
  filename: string;
  title?: string;
  description?: string;
  file_size: number;
  content_type: string;
  sha256: string;
}

export interface UploadInitResponse {
  document: DocumentOut;
  upload_url: string;
}

export interface FileUrlResponse {
  url: string;
  expires_in: number;
}

export interface SourceChunk {
  n: number;
  chunk_id: number;
  document_id: string;
  document_title: string;
  page_start: number;
  page_end: number;
  section: string | null;
  excerpt: string;
  score: number;
}

export interface Timings {
  embedding_ms: number;
  retrieval_ms: number;
  llm_ms: number;
  total_ms: number;
}

export interface ChatResponse {
  answer: string;
  status: "answered" | "insufficient_context";
  grounded: boolean;
  citations: SourceChunk[];
  retrieved: SourceChunk[];
  timings: Timings;
  model: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  database: boolean;
  embedder_loaded: boolean;
  embedding_model: string;
  llm_configured: boolean;
  llm_model: string;
  storage_configured: boolean;
}

export interface StatsResponse {
  documents_total: number;
  documents_by_status: Partial<Record<DocumentStatus, number>>;
  chunks_total: number;
  pages_total: number;
  embedding_model: string;
  llm_model: string;
}

export interface SessionResponse {
  admin: boolean;
}
