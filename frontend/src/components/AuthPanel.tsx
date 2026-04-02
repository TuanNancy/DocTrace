"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

interface AuthPanelProps {
  displayName: string | null;
  userEmail: string | null;
  avatarUrl?: string | null;
  loading: boolean;
  onSignOut: () => Promise<void>;
}

export function AuthPanel({
  displayName,
  userEmail,
  avatarUrl,
  loading,
  onSignOut,
}: AuthPanelProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const initials = useMemo(() => {
    const source = (displayName || userEmail || "U").trim();
    return source.charAt(0).toUpperCase();
  }, [displayName, userEmail]);

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, []);

  if (userEmail) {
    return (
      <div ref={containerRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 rounded-full border border-slate-300 bg-white/90 px-2 py-1 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800/90 dark:hover:bg-slate-700"
          aria-label="Open account menu"
        >
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt="Google avatar"
              className="h-8 w-8 rounded-full object-cover"
            />
          ) : (
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-100">
              {initials}
            </div>
          )}
        </button>

        {open && (
          <div className="absolute right-0 z-20 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-center gap-3">
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt="Google avatar"
                  className="h-10 w-10 rounded-full object-cover"
                />
              ) : (
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-200 text-sm font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-100">
                  {initials}
                </div>
              )}
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {displayName || "Baymax user"}
                </p>
                <p className="truncate text-xs text-slate-600 dark:text-slate-300">
                  {userEmail}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onSignOut}
              disabled={loading}
              className="mt-3 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            >
              {loading ? "Đang xử lý..." : "Sign out"}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Link
        href="/auth/login"
        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
      >
        Sign in
      </Link>
      <Link
        href="/auth/signup"
        className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600"
      >
        Sign up
      </Link>
    </div>
  );
}
