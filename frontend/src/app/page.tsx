"use client";

import { useEffect, useMemo, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { ChatWindow } from "@/components/ChatWindow";
import { AuthPanel } from "@/components/AuthPanel";
import { BrandMark } from "@/components/BrandMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UploadZone } from "@/components/UploadZone";
import { createClient } from "@/lib/client";
import type { UploadResponse } from "@/types";

export default function Home() {
  const [docId, setDocId] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
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

  const handleSignOut = async () => {
    setAuthLoading(true);
    setAuthError(null);
    const { error } = await supabase.auth.signOut();
    if (error) {
      setAuthError(error.message);
    }
    setDocId(null);
    setAuthLoading(false);
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

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 dark:bg-slate-900">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-rose-200 bg-rose-50/95 px-4 py-3 backdrop-blur dark:border-rose-900/40 dark:bg-rose-950/35">
        <BrandMark refreshOnClick />
        <div className="flex items-center gap-3">
          <AuthPanel
            displayName={displayName}
            userEmail={user?.email ?? null}
            avatarUrl={avatarUrl}
            loading={authLoading}
            onSignOut={handleSignOut}
          />
          <ThemeToggle />
        </div>
      </header>

      {authError && (
        <div className="mx-4 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/30 dark:text-red-300 md:mx-auto md:max-w-4xl">
          {authError}
        </div>
      )}

      <main className="flex flex-1 flex-col gap-4 p-4 md:mx-auto md:max-w-4xl md:gap-6 md:p-6">
        {!authReady && (
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
            Đang kiểm tra phiên đăng nhập...
          </div>
        )}
        <section>
          <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">
            Tải tài liệu
          </h2>
          {isAuthed ? (
            <UploadZone
              onUploadComplete={handleUploadComplete}
              mock={mock}
              accessToken={accessToken}
            />
          ) : authReady ? (
            <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
              Vui lòng đăng nhập để tải tài liệu PDF.
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
              Đang tải...
            </div>
          )}
        </section>

        <section className="flex flex-1 flex-col min-h-[400px] md:min-h-[480px]">
          <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-400">
            Hỏi đáp
          </h2>
          <div className="flex-1 min-h-0">
            {isAuthed ? (
              <ChatWindow docId={docId} mock={mock} accessToken={accessToken} />
            ) : authReady ? (
              <div className="flex h-full min-h-[220px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
                Đăng nhập để bắt đầu chat với tài liệu của bạn.
              </div>
            ) : (
              <div className="flex h-full min-h-[220px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
                Đang tải...
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 py-2 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
        {mock ? "Chưa kết nối backend — chế độ demo" : "Đã kết nối backend"}
      </footer>
    </div>
  );
}
