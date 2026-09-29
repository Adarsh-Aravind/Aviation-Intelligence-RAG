import { toast } from "sonner";

import { api } from "./api";

/** Open the source PDF at a page in a new tab (signed, short-lived URL). */
export async function openDocumentAtPage(documentId: string, page: number) {
  // Open the tab synchronously so popup blockers allow it, then point it at the signed URL.
  const win = window.open("about:blank", "_blank");
  try {
    const { url } = await api.fileUrl(documentId);
    const target = `${url}#page=${page}`;
    if (win) {
      win.opener = null;
      win.location.href = target;
    } else {
      window.open(target, "_blank", "noopener"); // popup was blocked — try once more
    }
  } catch (err) {
    win?.close();
    toast.error(err instanceof Error ? err.message : "Could not open document");
  }
}
