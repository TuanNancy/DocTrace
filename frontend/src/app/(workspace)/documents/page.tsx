"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog } from "@base-ui/react/dialog";
import { ArrowUpRight, BookOpen, FileText, MessageSquare, RefreshCw, Search, Trash2, X } from "lucide-react";
import { UploadZone } from "@/components/UploadZone";
import { DocumentStatus, formatBytes } from "@/components/workspace/DocumentStatus";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { openDocumentFile } from "@/lib/api";
import type { LibraryDocument } from "@/types";

export default function DocumentsPage() {
  const workspace = useWorkspace();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [deleting, setDeleting] = useState<LibraryDocument | null>(null);
  const documents = workspace.documents.filter((document) => document.name.toLocaleLowerCase("vi").includes(query.toLocaleLowerCase("vi"))
    && (filter === "all" || (filter === "pending" ? ["uploading", "queued", "processing", "deleting"].includes(document.status)
      : filter === "error" ? ["error", "delete_error"].includes(document.status) : document.status === filter)));
  const ready = workspace.documents.filter((document) => document.status === "ready").length;
  return <section className="glass-panel min-h-0 flex-1 overflow-y-auto p-5 sm:p-8">
    <div className="mx-auto max-w-5xl">
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div><p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-blue-500">Tri thức trong tầm tay</p>
          <h2 className="font-sans text-3xl font-semibold tracking-tight">Mọi tài liệu, một nơi.</h2>
          <p className="mt-3 max-w-lg text-sm leading-6 text-slate-500">Xây dựng thư viện của riêng bạn. Tải lên PDF, theo dõi xử lý và bắt đầu cuộc trò chuyện với tài liệu.</p></div>
        <div className="flex items-center gap-3 rounded-2xl border border-white bg-white/60 px-5 py-4"><BookOpen size={22} className="text-blue-400" strokeWidth={1.4} />
          <div><p className="text-xl font-semibold tracking-tight">{ready}<span className="ml-1 text-sm font-normal text-slate-400">/ {workspace.documents.length}</span></p><p className="text-[10px] text-slate-400">tài liệu sẵn sàng</p></div></div>
      </div>
      <UploadZone session={workspace.upload} />
      <div className="mb-5 mt-8 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <h3 className="text-sm font-semibold">Tất cả tài liệu <span className="ml-1 text-xs font-normal text-slate-400">({documents.length})</span></h3>
        <div className="flex flex-wrap gap-2">
          <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-slate-400"><Search size={15} />
            <input className="w-full min-w-0 bg-transparent text-xs text-slate-700 outline-none sm:w-40" placeholder="Tìm tên tài liệu…" aria-label="Tìm tài liệu" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
          <select className="rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-xs text-slate-600" value={filter} aria-label="Lọc trạng thái" onChange={(event) => setFilter(event.target.value)}>
            <option value="all">Mọi trạng thái</option><option value="ready">Sẵn sàng</option><option value="pending">Đang xử lý</option><option value="error">Có lỗi</option>
          </select>
          <button className="icon-button" aria-label="Làm mới thư viện" onClick={() => void workspace.refresh()}><RefreshCw size={16} /></button>
        </div>
      </div>
      {workspace.libraryError && <div role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">{workspace.libraryError}</div>}
      {workspace.documentsLoading ? <div className="space-y-3" role="status" aria-label="Đang tải tài liệu">{[1, 2, 3].map((i) => <div key={i} className="h-20 animate-pulse rounded-2xl bg-slate-100/70" />)}</div>
        : !documents.length ? <div className="rounded-2xl border border-dashed border-slate-200 py-14 text-center"><FileText size={32} className="mx-auto mb-4 text-blue-200" strokeWidth={1.3} />
          <p className="font-sans text-lg font-semibold">{workspace.documents.length ? "Chưa tìm thấy tài liệu phù hợp" : "Thư viện đang chờ tài liệu đầu tiên"}</p>
          <p className="mt-2 text-xs text-slate-400">{workspace.documents.length ? "Thử đổi từ khóa hoặc bộ lọc trạng thái." : "Thêm một PDF ở phía trên để bắt đầu khám phá."}</p></div>
          : <div>
            <div className="mb-2 hidden grid-cols-[minmax(0,1fr)_135px_180px] gap-4 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-400 md:grid"><span>Tài liệu</span><span>Trạng thái</span><span className="text-right">Thao tác</span></div>
            <ul className="space-y-2.5">{documents.map((document) => {
              const busy = workspace.busyIds.includes(document.doc_id);
               const removing = ["deleting", "deleted"].includes(document.status);
               const processing = ["uploading", "queued", "processing"].includes(document.status);
              return <li key={document.doc_id} className="document-row" data-testid="document-row">
                <div className="flex min-w-0 items-start gap-3"><div className="flex h-11 w-10 shrink-0 flex-col items-center justify-center gap-0.5 rounded-xl border border-blue-100/60 bg-blue-50/80 text-blue-400"><FileText size={19} strokeWidth={1.4} /><span className="text-[7px] font-bold tracking-wider">PDF</span></div>
                  <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-slate-700" title={document.name}>{document.name}</p>
                    <p className="mt-1.5 text-[10px] text-slate-400">{formatBytes(document.size_bytes)}<span className="mx-2">·</span>{new Date(document.created_at).toLocaleDateString("vi-VN")}{document.chunks_count > 0 && <><span className="mx-2">·</span>{document.chunks_count} đoạn</>}</p>
                    {document.error && <p className="mt-2 text-xs leading-5 text-red-600">{document.error}</p>}
                    {document.warnings?.map((warning) => <p key={warning} className="mt-2 text-xs leading-5 text-amber-700">{warning}</p>)}
                  </div></div>
                <div className="ml-[52px] md:ml-0"><DocumentStatus status={document.status} /></div>
                <div className="ml-[52px] flex flex-wrap items-center gap-1.5 md:ml-0 md:justify-end">
                  {document.status === "ready" && <button className="secondary-button px-2.5 py-2 text-[11px]" onClick={() => { workspace.selectDocument(document); router.push("/chat"); }}><MessageSquare size={13} />Hỏi đáp</button>}
                  {["error", "delete_error"].includes(document.status) && <button className="secondary-button px-2.5 py-2 text-[11px]" disabled={busy} onClick={() => void workspace.operate(document, "retry")}><RefreshCw size={13} />Thử lại</button>}
                  {!workspace.mock && <button className="icon-button" aria-label={`Xem PDF ${document.name}`} title="Xem PDF" disabled={removing || document.status === "uploading" || document.status === "delete_error"} onClick={async () => {
                    try { await openDocumentFile(document.doc_id, workspace.accessToken!); }
                    catch (cause) { workspace.setNotice(cause instanceof Error ? cause.message : "Không thể mở PDF."); }
                  }}><ArrowUpRight size={16} /></button>}
                  <button className="icon-button hover:!bg-red-50 hover:!text-red-500" aria-label={`Xóa ${document.name}`} title={processing ? "Chờ xử lý hoàn tất trước khi xóa" : "Xóa tài liệu"} disabled={busy || removing || processing} onClick={() => setDeleting(document)}><Trash2 size={15} /></button>
                </div>
              </li>;
            })}</ul>
          </div>}
      <p className="mt-6 text-center text-[10px] leading-5 text-slate-400">PDF của bạn được lưu riêng theo tài khoản · Tài liệu đã xử lý có thể dùng ngay trong chat</p>
    </div>
    <Dialog.Root open={!!deleting} onOpenChange={(open) => { if (!open) setDeleting(null); }}>
      <Dialog.Portal><Dialog.Backdrop className="fixed inset-0 z-50 bg-slate-900/20 backdrop-blur-sm" />
        <Dialog.Popup className="workspace glass-panel fixed left-1/2 top-1/2 z-50 w-[min(90vw,420px)] -translate-x-1/2 -translate-y-1/2 p-6">
          <div className="flex items-center justify-between"><Dialog.Title className="font-sans text-xl font-semibold">Xóa tài liệu?</Dialog.Title><Dialog.Close className="icon-button" aria-label="Đóng xác nhận"><X size={17} /></Dialog.Close></div>
          <Dialog.Description className="mt-3 break-words text-sm leading-6 text-slate-500">PDF “{deleting?.name}” và dữ liệu đã xử lý sẽ được xóa khỏi thư viện.</Dialog.Description>
          <div className="mt-6 flex justify-end gap-2"><Dialog.Close className="secondary-button">Giữ lại</Dialog.Close>
            <button className="primary-button !bg-red-500 hover:!bg-red-600" onClick={() => { if (deleting) void workspace.operate(deleting, "delete"); setDeleting(null); }}>Xóa tài liệu</button></div>
        </Dialog.Popup></Dialog.Portal>
    </Dialog.Root>
  </section>;
}
