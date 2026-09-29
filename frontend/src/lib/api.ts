// Typed browser client. Talks ONLY to this app's own /api routes — never to the backend directly,
// so no secret ever reaches the browser.
import type {
  ChatResponse,
  DocumentList,
  DocumentOut,
  FileUrlResponse,
  HealthResponse,
  SessionResponse,
  StatsResponse,
  UploadInitRequest,
  UploadInitResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown,
  ) {
    super(message);
  }
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  if (status === 429) return "Too many requests — please wait a moment.";
  if (status >= 500) return "The service is temporarily unavailable. Please try again.";
  return `Request failed (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Network error — check your connection.", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(messageFrom(body, res.status), res.status, body);
  return body as T;
}

const p = (path: string) => `/api/proxy/${path}`;

export const api = {
  health: () => request<HealthResponse>(p("health")),
  stats: () => request<StatsResponse>(p("stats")),
  documents: () => request<DocumentList>(p("documents")),
  document: (id: string) => request<DocumentOut>(p(`documents/${id}`)),
  fileUrl: (id: string) => request<FileUrlResponse>(p(`documents/${id}/file-url`)),
  initUpload: (body: UploadInitRequest) =>
    request<UploadInitResponse>(p("documents/init"), { method: "POST", body: JSON.stringify(body) }),
  completeUpload: (id: string) =>
    request<DocumentOut>(p(`documents/${id}/complete`), { method: "POST" }),
  reprocess: (id: string) => request<DocumentOut>(p(`documents/${id}/reprocess`), { method: "POST" }),
  deleteDocument: (id: string) => request<void>(p(`documents/${id}`), { method: "DELETE" }),
  ask: (question: string) =>
    request<ChatResponse>(p("chat"), { method: "POST", body: JSON.stringify({ question }) }),

  session: () => request<SessionResponse>("/api/auth/session"),
  login: (password: string) =>
    request<SessionResponse>("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) }),
  logout: () => request<SessionResponse>("/api/auth/logout", { method: "POST" }),
};

/** PUT the file straight to Supabase Storage via the one-time signed URL, with progress events. */
export function uploadToSignedUrl(
  url: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", "application/pdf");
    xhr.setRequestHeader("x-upsert", "true");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(`Upload to storage failed (${xhr.status})`, xhr.status));
    xhr.onerror = () => reject(new ApiError("Upload failed — network error.", 0));
    xhr.send(file);
  });
}
