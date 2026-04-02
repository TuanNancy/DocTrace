"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { ChatWindow, type ChatWindowHandle } from "@/components/ChatWindow";
import { BrandMark } from "@/components/BrandMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UploadZone } from "@/components/UploadZone";
import { createClient } from "@/lib/client";
import type { UploadResponse } from "@/types";

const HISTORY_TODAY = [
  { title: "Phân tích tài liệu PDF", time: "10:30" },
  { title: "Hỏi đáp về AI", time: "09:15" },
];

const HISTORY_YESTERDAY = [
  { title: "Tóm tắt văn bản", time: "Hôm qua" },
  { title: "Dịch thuật", time: "Hôm qua" },
];

export default function Home() {
  const router = useRouter();
  const chatRef = useRef<ChatWindowHandle>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const backendUrl = process.env.NEXT_PUBLIC_API_URL as string | undefined;
  const mock = !backendUrl;
  const supabase = useMemo(() => createClient(), []);

  const handleUploadComplete = (res: UploadResponse) => {
    setDocId(res.doc_id);
  };

  useEffect(() => {
    let mounted = true;

    const bootstrapUser = async () => {
      const [{ data: userData, error: userError }, { data: sessionData }] = await Promise.all([
        supabase.auth.getUser(),
        supabase.auth.getSession(),
      ]);
      if (!mounted) return;
      const sessionUser = sessionData.session?.user ?? null;
      const resolvedUser = userData.user ?? sessionUser;
      setUser(resolvedUser);
      setAccessToken(sessionData.session?.access_token ?? null);
      if (userError && !resolvedUser) {
        setAuthError(userError.message);
      }
      setAuthReady(true);
    };

    bootstrapUser();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      setAccessToken(session?.access_token ?? null);
      setAuthReady(true);
      if (!session?.user) {
        setDocId(null);
      }
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [supabase]);

  useEffect(() => {
    if (!profileMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setProfileMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [profileMenuOpen]);

  const handleSignOut = async () => {
    setProfileMenuOpen(false);
    setAuthLoading(true);
    setAuthError(null);
    const { error } = await supabase.auth.signOut();
    if (error) {
      setAuthError(error.message);
      setAuthLoading(false);
      return;
    }
    setDocId(null);
    setAuthLoading(false);
    router.replace("/auth/login");
    router.refresh();
  };

  const isAuthed = !!user && !!accessToken;
  const displayName =
    (user?.user_metadata?.full_name as string | undefined) ??
    (user?.user_metadata?.name as string | undefined) ??
    null;
  const avatarUrl =
    (user?.user_metadata?.avatar_url as string | undefined) ??
    (user?.user_metadata?.picture as string | undefined) ??
    null;

  const initials = (displayName || user?.email || "U").trim().charAt(0).toUpperCase();

  const startNewChat = () => {
    chatRef.current?.clear();
  };

  const clearChat = () => {
    if (typeof window !== "undefined" && window.confirm("Bạn có chắc muốn xóa toàn bộ cuộc trò chuyện?")) {
      chatRef.current?.clear();
    }
  };

  const exportChat = () => {
    chatRef.current?.exportTranscript();
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#f7f7f4] dark:bg-slate-900">
      {authError && (
        <div className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/30 dark:text-red-300">
          {authError}
        </div>
      )}

      <div className="relative flex min-h-0 flex-1">
        {/* Mobile backdrop */}
        {sidebarOpen && (
          <button
            type="button"
            aria-label="Đóng sidebar"
            className="fixed inset-0 z-30 bg-black/40 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Sidebar — cấu trúc giống mẫu, màu theo project */}
        <aside
          className={`fixed inset-y-0 left-0 z-40 flex w-[280px] shrink-0 flex-col border-r border-[#B22222]/20 bg-slate-900 text-white transition-all duration-300 ease-out dark:bg-slate-950 md:static md:z-auto ${
            sidebarOpen
              ? "translate-x-0 md:w-[280px]"
              : "-translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden md:border-0"
          }`}
        >
          <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-5 py-6">
            <div className="min-w-0">
              <BrandMark compact variant="onDark" />
            </div>
          </div>

          <button
            type="button"
            onClick={startNewChat}
            className="mx-5 mt-4 flex shrink-0 items-center justify-center gap-2 rounded-lg bg-[#B22222] px-4 py-3 text-sm font-medium text-white transition hover:bg-[#9a1d1d]"
          >
            <span className="text-lg leading-none">+</span>
            Cuộc trò chuyện mới
          </button>

          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
            <p className="px-3 pb-2 pt-4 text-[0.65rem] font-semibold uppercase tracking-wider text-white/50">
              Hôm nay
            </p>
            <ul className="space-y-1">
              {HISTORY_TODAY.map((item) => (
                <li
                  key={item.title}
                  className="flex cursor-pointer items-start gap-3 rounded-lg px-3 py-3 text-sm transition hover:bg-white/10"
                >
                  <span className="mt-0.5 text-[#B22222]">💬</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{item.title}</div>
                    <div className="text-xs text-white/50">{item.time}</div>
                  </div>
                </li>
              ))}
            </ul>
            <p className="px-3 pb-2 pt-6 text-[0.65rem] font-semibold uppercase tracking-wider text-white/50">
              Hôm qua
            </p>
            <ul className="space-y-1">
              {HISTORY_YESTERDAY.map((item) => (
                <li
                  key={item.title}
                  className="flex cursor-pointer items-start gap-3 rounded-lg px-3 py-3 text-sm transition hover:bg-white/10"
                >
                  <span className="mt-0.5 text-[#B22222]">💬</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{item.title}</div>
                    <div className="text-xs text-white/50">{item.time}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="shrink-0 border-t border-white/10 px-4 py-4">
            {isAuthed ? (
              <div ref={profileMenuRef} className="relative">
                <button
                  type="button"
                  onClick={() => setProfileMenuOpen((v) => !v)}
                  className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition hover:bg-white/10"
                  aria-expanded={profileMenuOpen}
                  aria-haspopup="true"
                >
                  {avatarUrl ? (
                    <img src={avatarUrl} alt="" className="h-10 w-10 shrink-0 rounded-full object-cover" />
                  ) : (
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#B22222] to-[#7a1818] text-sm font-semibold text-white">
                      {initials}
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{displayName || "Baymax user"}</div>
                    <div className="truncate text-xs text-white/50">{user?.email}</div>
                  </div>
                </button>
                {profileMenuOpen && (
                  <div
                    className="absolute bottom-full left-0 right-0 z-50 mb-2 space-y-2 rounded-lg border border-white/15 bg-slate-800 p-2 shadow-xl"
                    role="menu"
                  >
                    <ThemeToggle className="w-full justify-center border-white/20 bg-white/5 text-white hover:bg-white/10 dark:border-white/20 dark:bg-white/5 dark:text-white dark:hover:bg-white/10" />
                    <button
                      type="button"
                      role="menuitem"
                      onClick={handleSignOut}
                      disabled={authLoading}
                      className="w-full rounded-lg border border-white/20 bg-white/5 px-3 py-2 text-sm font-medium text-white transition hover:bg-white/10 disabled:opacity-50"
                    >
                      {authLoading ? "Đang xử lý..." : "Đăng xuất"}
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-2 text-center">
                <p className="text-xs text-white/50">Đăng nhập để lưu lịch sử</p>
                <Link
                  href="/auth/login"
                  className="block w-full rounded-lg bg-[#B22222] px-3 py-2 text-center text-sm font-medium text-white transition hover:bg-[#9a1d1d]"
                >
                  Đăng nhập
                </Link>
              </div>
            )}
          </div>
        </aside>

        {/* Main */}
        <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-white dark:bg-slate-900">
          <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => setSidebarOpen((v) => !v)}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-600 transition hover:bg-[#f7f7f4] hover:text-[#B22222] dark:text-slate-300 dark:hover:bg-slate-800"
                aria-label="Ẩn hiện sidebar"
              >
                <span className="text-xl">☰</span>
              </button>
              <h1 className="truncate text-lg font-semibold text-slate-900 dark:text-slate-100">
              Tìm kiếm & tóm tắt tài liệu
              </h1>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={clearChat}
                className="hidden items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 transition hover:border-[#B22222]/40 hover:bg-[#f7f7f4] hover:text-[#B22222] sm:inline-flex dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                🗑 Xóa chat
              </button>
              <button
                type="button"
                onClick={exportChat}
                className="hidden items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 transition hover:border-[#B22222]/40 hover:bg-[#f7f7f4] hover:text-[#B22222] sm:inline-flex dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                ⬇ Xuất file
              </button>
            </div>
          </header>

          <section className="shrink-0 border-b border-slate-200 bg-[#f7f7f4] px-4 py-5 dark:border-slate-700 dark:bg-slate-900/50">
            <div className="mx-auto w-full max-w-[800px]">
              <p className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400"></p>
              {!authReady ? (
                <div className="flex h-[104px] items-center rounded-xl border border-slate-200 bg-white px-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
                  Đang kiểm tra phiên đăng nhập...
                </div>
              ) : isAuthed ? (
                <div className="h-[104px] w-full">
                  <UploadZone
                    onUploadComplete={handleUploadComplete}
                    mock={mock}
                    accessToken={accessToken}
                    compact
                  />
                </div>
              ) : (
                <div className="flex h-[104px] items-center rounded-xl border border-slate-200 bg-white px-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
                  Vui lòng đăng nhập để tải tài liệu PDF.
                </div>
              )}
            </div>
          </section>

          <div className="flex min-h-0 flex-1 flex-col">
            {!authReady ? (
              <div className="flex flex-1 items-center justify-center p-8 text-sm text-slate-600 dark:text-slate-400">
                Đang kiểm tra phiên đăng nhập...
              </div>
            ) : isAuthed ? (
              <ChatWindow
                ref={chatRef}
                docId={docId}
                mock={mock}
                accessToken={accessToken}
                variant="shell"
              />
            ) : (
              <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-slate-600 dark:text-slate-400">
                Đăng nhập để bắt đầu chat với tài liệu của bạn.
              </div>
            )}
          </div>
        </main>
      </div>

      <footer className="shrink-0 border-t border-slate-200 py-1.5 text-center text-[10px] text-slate-500 dark:border-slate-700 dark:text-slate-500">
        {mock ? "Chưa kết nối backend — chế độ demo" : "Đã kết nối backend"}
      </footer>
    </div>
  );
}
