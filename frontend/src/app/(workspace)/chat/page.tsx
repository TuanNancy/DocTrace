"use client";

import { BookOpen, Download, FileText } from "lucide-react";
import { ChatWindow } from "@/components/ChatWindow";
import { Drawer } from "@/components/workspace/Drawer";
import { DocumentPanel } from "@/components/workspace/DocumentPanel";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";

export default function ChatPage() {
  const workspace = useWorkspace();
  return <div className="flex min-h-0 flex-1 gap-5">
    <section className="glass-panel flex min-w-0 flex-1 flex-col overflow-hidden">
      <header className="flex min-h-[65px] shrink-0 items-center justify-between gap-2 border-b border-slate-100/80 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5"><FileText size={17} className="shrink-0 text-blue-400" />
          <div className="min-w-0"><p className="truncate text-xs font-medium text-slate-700">{workspace.activeDocument?.name ?? "Chọn tài liệu để bắt đầu"}</p>
            <p className="mt-1 text-[10px] text-slate-400">{workspace.activeDocument ? "Sẵn sàng khám phá cùng bạn" : "Không gian hỏi đáp riêng của bạn"}</p></div>
        </div>
        <div className="flex shrink-0 gap-1">
          <button className="icon-button" aria-label="Xuất hội thoại" title="Xuất hội thoại" disabled={!workspace.chat.messages.length} onClick={workspace.chat.exportTranscript}><Download size={17} /></button>
          <button className="icon-button xl:hidden" aria-label="Mở tài liệu và nguồn" onClick={() => workspace.setSourcesOpen(true)}><BookOpen size={18} /></button>
          <span className="ml-1 hidden items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] text-emerald-600 sm:inline-flex"><span className="h-1 w-1 rounded-full bg-emerald-500" />{workspace.chat.loading ? "Đang trả lời" : "Sẵn sàng"}</span>
        </div>
      </header>
      <ChatWindow docId={workspace.docId} mock={workspace.mock} session={workspace.chat} onSelectSource={workspace.selectSource} />
    </section>
    <aside className="glass-panel hidden w-[290px] shrink-0 flex-col overflow-y-auto xl:flex 2xl:w-[320px]"><DocumentPanel /></aside>
    <div className="xl:hidden"><Drawer open={workspace.sourcesOpen} onOpenChange={workspace.setSourcesOpen} title={workspace.source ? "Trích dẫn nguồn" : "Tài liệu của bạn"}><DocumentPanel /></Drawer></div>
  </div>;
}
