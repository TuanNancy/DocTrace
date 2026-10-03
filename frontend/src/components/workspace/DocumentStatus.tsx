import { LoaderCircle } from "lucide-react";
import { isPending } from "@/lib/documents";
import type { DocumentStatus as Status } from "@/types";

const labels: Record<Status, string> = {
  queued: "Chờ xử lý", processing: "Đang xử lý", ready: "Sẵn sàng",
  error: "Lỗi xử lý", deleting: "Đang xóa", delete_error: "Lỗi xóa", deleted: "Đã xóa",
};
const classes: Record<Status, string> = {
  queued: "status-queued", processing: "status-processing", ready: "status-ready",
  error: "status-error", deleting: "status-deleting", delete_error: "status-delete_error", deleted: "status-deleted",
};

export function DocumentStatus({ status }: { status: Status }) {
  const pending = isPending(status);
  return <span className={`status-badge ${classes[status]}`}>{pending && <LoaderCircle size={11} className="animate-spin" />}{labels[status]}</span>;
}
