"use client";

import Link from "next/link";
import { ArrowUpRight, BookOpen, Check, FileText, RefreshCw } from "lucide-react";
import { UploadZone } from "@/components/UploadZone";
import { useWorkspace } from "./WorkspaceProvider";
import { CitationPanel } from "./CitationPanel";
import { DocumentStatus } from "./DocumentStatus";

export function DocumentPanel() {
  const workspace = useWorkspace();
  if (workspace.source) return <CitationPanel />;
  return <div className="flex flex-1 flex-col p-5">
    <div className="mb-5 flex items-center justify-between"><h2 className="font-sans text-lg font-semibold">Tài liệu của bạn</h2><span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-500">{workspace.documents.length}</span></div>
    <UploadZone compact session={workspace.upload} />
    <div className="my-5 flex items-center justify-between"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Chọn PDF để hỏi đáp</p>
      <button className="icon-button" aria-label="Làm mới tài liệu" onClick={() => void workspace.refresh()}><RefreshCw size={13} /></button></div>
    {workspace.libraryError && <p role="alert" className="mb-4 text-xs leading-5 text-red-600">{workspace.libraryError}</p>}
    {workspace.documentsLoading ? <p className="animate-pulse text-xs text-slate-400">Đang tải thư viện…</p>
      : !workspace.documents.length ? <div className="py-8 text-center"><BookOpen size={24} className="mx-auto mb-3 text-slate-300" strokeWidth={1.3} /><p className="text-xs text-slate-400">Một thư viện mới, nhiều điều để khám phá.</p></div>
        : <ul className="space-y-2">{workspace.documents.slice(0, 12).map((document) => <li key={document.doc_id}>
          <button className={`document-choice ${workspace.docId === document.doc_id ? "document-choice-active" : ""}`} disabled={document.status !== "ready"} onClick={() => workspace.selectDocument(document)}>
            <FileText size={18} className="mt-0.5 shrink-0 text-blue-400" strokeWidth={1.5} />
            <span className="min-w-0 flex-1 text-left"><span className="mb-2 block truncate text-xs font-medium">{document.name}</span><DocumentStatus status={document.status} /></span>
            {workspace.docId === document.doc_id && <Check size={14} className="mt-1 text-blue-500" />}
          </button>
        </li>)}</ul>}
    <Link href="/documents" onClick={() => workspace.setSourcesOpen(false)} className="mt-5 flex items-center justify-center gap-1.5 text-xs font-medium text-blue-500 hover:text-blue-700">Quản lý thư viện <ArrowUpRight size={14} /></Link>
    <div className="mt-auto pt-7"><p className="border-t border-slate-100 pt-4 text-[10px] leading-5 text-slate-400">Tài liệu được lưu riêng theo tài khoản. Hội thoại chỉ giữ trong phiên hiện tại.</p></div>
  </div>;
}
