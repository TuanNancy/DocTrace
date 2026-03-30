"use client";

import { useState } from "react";
import { ChatWindow } from "@/components/ChatWindow";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UploadZone } from "@/components/UploadZone";
import type { UploadResponse } from "@/types";

export default function Home() {
  const [docId, setDocId] = useState<string | null>(null);
  const backendUrl = process.env.NEXT_PUBLIC_API_URL as string | undefined;
  const mock = !backendUrl;

  const handleUploadComplete = (res: UploadResponse) => {
    setDocId(res.doc_id);
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 dark:bg-slate-900">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
        <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
          RAG PDF Chatbot
        </h1>
        <ThemeToggle />
      </header>

      <main className="flex flex-1 flex-col gap-4 p-4 md:mx-auto md:max-w-4xl md:gap-6 md:p-6">
        <section>
          <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">
            Tải tài liệu
          </h2>
          <UploadZone
            onUploadComplete={handleUploadComplete}
            mock={mock}
          />
        </section>

        <section className="flex flex-1 flex-col min-h-[400px] md:min-h-[480px]">
          <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">
            Hỏi đáp
          </h2>
          <div className="flex-1 min-h-0">
            <ChatWindow docId={docId} mock={mock} />
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 py-2 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        {mock ? "Chưa kết nối backend — chế độ demo" : "Đã kết nối backend"}
      </footer>
    </div>
  );
}
