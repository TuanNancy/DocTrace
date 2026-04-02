"use client";

import Link from "next/link";

interface AuthPanelProps {
  userEmail: string | null;
  loading: boolean;
  onSignOut: () => Promise<void>;
}

export function AuthPanel({
  userEmail,
  loading,
  onSignOut,
}: AuthPanelProps) {
  if (userEmail) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-600 dark:text-slate-300">
          {userEmail}
        </span>
        <button
          type="button"
          onClick={onSignOut}
          disabled={loading}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          {loading ? "Đang xử lý..." : "Sign out"}
        </button>
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
