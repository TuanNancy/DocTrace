import Link from "next/link";

export default function AuthCodeErrorPage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-4">
      <div className="w-full rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800/50">
        <h1 className="mb-2 text-xl font-semibold text-slate-800 dark:text-slate-100">
          OAuth callback error
        </h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Không thể hoàn tất đăng nhập Google. Vui lòng thử lại.
        </p>
        <Link
          href="/auth/login"
          className="mt-4 inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600"
        >
          Quay lại Sign in
        </Link>
      </div>
    </main>
  );
}
