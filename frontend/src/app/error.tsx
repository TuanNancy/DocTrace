"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 p-4 dark:bg-slate-900">
      <h2 className="text-lg font-medium text-slate-800 dark:text-slate-100">
        Có lỗi xảy ra
      </h2>
      <p className="max-w-md text-center text-sm text-slate-600 dark:text-slate-400">
        {error.message}
      </p>
      <button
        type="button"
        onClick={reset}
        className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600"
      >
        Thử lại
      </button>
    </div>
  );
}
