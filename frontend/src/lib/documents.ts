import type { DocumentStatus } from "@/types";

export function isIndexing(status: DocumentStatus) {
  return status === "queued" || status === "processing";
}

export function isPending(status: DocumentStatus) {
  return isIndexing(status) || status === "deleting";
}

export function formatBytes(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
