import { LoaderCircle } from "lucide-react";
import type { DocumentStatus as Status } from "@/types";

const labels: Record<Status, string> = {
  uploading: "Đang tải", queued: "Chờ xử lý", processing: "Đang xử lý", ready: "Sẵn sàng",
  error: "Lỗi xử lý", deleting: "Đang xóa", delete_error: "Lỗi xóa", deleted: "Đã xóa",
};
const classes: Record<Status, string> = {
  uploading: "status-uploading", queued: "status-queued", processing: "status-processing", ready: "status-ready",
  error: "status-error", deleting: "status-deleting", delete_error: "status-delete_error", deleted: "status-deleted",
};

export function DocumentStatus({ status }: { status: Status }) {
  const pending = ["uploading", "queued", "processing", "deleting"].includes(status);
  return <span className={`status-badge ${classes[status]}`}>{pending && <LoaderCircle size={11} className="animate-spin" />}{labels[status]}</span>;
}

export function formatBytes(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
