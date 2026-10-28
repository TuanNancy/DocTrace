"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Check, Copy, FileText, Sparkles, Square } from "lucide-react";
import Link from "next/link";
import type { ChatSource } from "@/types";
import type { ChatSession } from "@/lib/use-chat-session";
import { MessageMarkdown } from "./MessageMarkdown";
import { SourceCardList } from "./SourceCardList";

interface ChatWindowProps {
  docId: string | null;
  mock?: boolean;
  session: ChatSession;
  onSelectSource?: (source: ChatSource) => void;
}

function CopyMessage({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  return <button className="message-action" onClick={async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setFailed(false); }
    catch { setFailed(true); }
  }} aria-label="Sao chép câu trả lời">{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Đã sao chép" : failed ? "Không thể sao chép" : "Sao chép"}</button>;
}

export function ChatWindow({ docId, mock = false, session: chat, onSelectSource }: ChatWindowProps) {
  const scroll = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (stickToBottom.current) scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: "smooth" });
  }, [chat.messages]);
  useEffect(() => {
    if (!inputRef.current) return;
    inputRef.current.style.height = "auto";
    inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 150)}px`;
  }, [chat.input]);
  const hasDoc = !!docId || mock;
  return <div className="flex min-h-0 flex-1 flex-col">
    <div ref={scroll} onScroll={() => {
      const element = scroll.current;
      if (element) stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 100;
    }} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 sm:px-8">
      {chat.transcriptLoading ? <div role="status" className="flex h-full min-h-[310px] flex-col items-center justify-center gap-3 text-xs text-slate-400">
        <span className="h-6 w-6 animate-spin rounded-full border-2 border-blue-100 border-t-blue-400" />
        Đang tải hội thoại…
      </div> : chat.messages.length === 0 ? <div className="mx-auto flex h-full min-h-[310px] max-w-lg flex-col items-center justify-center py-10 text-center">
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-[22px] border border-white bg-gradient-to-br from-blue-50 to-white text-blue-500 shadow-[0_8px_30px_-10px_#93baff]"><Sparkles size={28} strokeWidth={1.4} /></div>
        <span className="mb-3 text-[10px] font-semibold uppercase tracking-[0.23em] text-blue-500">Một câu hỏi, nhiều khám phá</span>
        <h2 className="font-sans text-[27px] font-semibold leading-tight tracking-tight sm:text-[32px]">Bạn muốn tìm hiểu điều gì?</h2>
        <p className="mt-4 max-w-sm text-sm leading-6 text-slate-500">{hasDoc ? "Cùng tìm những ý chính, làm rõ thông tin và khám phá tài liệu — luôn có nguồn để đối chiếu." : "Tải lên một tệp PDF và đặt câu hỏi. DocTrace sẽ giúp bạn tìm câu trả lời kèm trích dẫn nguồn."}</p>
        {!hasDoc && <Link href="/documents" className="secondary-button mt-5 text-xs"><FileText size={15} /> Chọn tài liệu từ thư viện</Link>}
        <div className="mt-7 flex flex-wrap justify-center gap-2">
          {["Tóm tắt tài liệu", "Các điểm quan trọng là gì?", "Liệt kê các mốc thời gian"].map((question) =>
            <button key={question} className="suggestion-chip" disabled={!hasDoc || chat.resetting} onClick={() => { chat.setInput(question); inputRef.current?.focus(); }}>{question}</button>)}
        </div>
      </div> : <ol className="mx-auto max-w-3xl space-y-7 py-7" aria-label="Tin nhắn hội thoại">
        {chat.messages.map((message) => {
          const stale = message.sources?.some((item) => item.stale) ?? false;
          return <li key={message.id} className={message.role === "user" ? "flex justify-end" : ""}>
            {message.role === "user" ? <div className="max-w-[88%] whitespace-pre-wrap break-words rounded-[20px] rounded-br-md border border-blue-100/70 bg-[#eaf2ff] px-5 py-3 text-sm leading-6 text-slate-700">{message.content}</div>
              : <div className="min-w-0">
                <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-700"><span className="flex h-6 w-6 items-center justify-center rounded-lg bg-blue-500 text-white"><Sparkles size={13} /></span>DocTrace
                  {message.isStreaming && <span className="ml-1 text-[10px] font-normal text-blue-500">Đang đọc tài liệu…</span>}</div>
                {message.content ? <MessageMarkdown content={message.content} sources={message.sources} onSelectSource={stale ? undefined : onSelectSource} />
                  : message.isStreaming ? <div className="flex gap-1 py-2" aria-label="Đang tạo câu trả lời">{[0, 1, 2].map((dot) => <span key={dot} className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-300" style={{ animationDelay: `${dot * 150}ms` }} />)}</div> : null}
                {!!message.sources?.length && <SourceCardList sources={message.sources} onSelectSource={stale ? undefined : onSelectSource} />}
                {stale && <p className="mt-2 text-[10px] leading-5 text-amber-600">Nguồn trích dẫn không còn khả dụng sau khi tài liệu được xử lý lại.</p>}
                {!message.isStreaming && message.content && <div className="mt-3 flex items-center gap-3"><CopyMessage text={message.content} />{message.interrupted && <span className="text-[10px] text-slate-400">Câu trả lời đã dừng</span>}</div>}
              </div>}
          </li>;
        })}
      </ol>}
    </div>
    <div className="shrink-0 px-3 pb-3 pt-2 sm:px-6 sm:pb-4">
      {chat.resetting && <p role="status" className="mb-3 text-xs text-slate-500">Đang xóa hội thoại cũ…</p>}
      {chat.error && <div role="alert" className="mb-3 rounded-xl bg-red-50 p-3 text-xs text-red-700">{chat.error}</div>}
      {chat.retryMode && !chat.loading && <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <button type="button" className="secondary-button text-xs" disabled={chat.resetting || chat.transcriptLoading}
          onClick={() => void chat.retryLastRequest()}>{chat.retryMode === "same" ? "Kiểm tra / thử lại" : "Gửi lại (tính lượt mới)"}</button>
        <span>{chat.retryMode === "same" ? "Dùng lại mã yêu cầu để tránh tính thêm lượt cho câu hỏi đã nhận."
          : "Yêu cầu trước đã kết thúc; gửi lại sẽ dùng một lượt mới."}</span>
      </div>}
      <form onSubmit={(event) => { event.preventDefault(); stickToBottom.current = true; void chat.submit(); }} className="composer">
        <textarea ref={inputRef} value={chat.input} onChange={(event) => chat.setInput(event.target.value)} rows={1} maxLength={8000}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!chat.loading && !chat.transcriptLoading && !chat.resetting) event.currentTarget.form?.requestSubmit();
            }
          }} aria-label="Câu hỏi của bạn" placeholder={chat.resetting ? "Đang xóa hội thoại cũ…" : chat.transcriptLoading ? "Đang tải hội thoại…" : hasDoc ? "Nhập câu hỏi của bạn…" : "Chọn một PDF để bắt đầu…"}
          disabled={chat.loading || chat.transcriptLoading || chat.resetting || !hasDoc} className="max-h-[150px] min-h-11 flex-1 resize-none bg-transparent px-2 py-3 text-sm leading-5 text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-60" />
        {chat.loading ? <button type="button" onClick={chat.stop} className="send-button" aria-label="Dừng trả lời"><Square size={16} fill="currentColor" /></button>
          : <button type="submit" className="send-button" disabled={!hasDoc || chat.transcriptLoading || chat.resetting || !chat.input.trim()} aria-label="Gửi"><ArrowUp size={19} /></button>}
      </form>
      <p className="mt-2.5 text-center text-[10px] leading-4 text-slate-400">Câu trả lời dựa trên tài liệu của bạn · Bấm vào trích dẫn để xem nguồn</p>
    </div>
  </div>;
}
