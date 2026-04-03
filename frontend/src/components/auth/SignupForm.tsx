"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useFormState } from "react-dom";
import { useRouter } from "next/navigation";
import { signupAction } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/AuthSubmitButton";
import { BrandMark } from "@/components/BrandMark";

type AuthActionState = {
  status: "idle" | "success" | "error";
  message: string;
};

const INITIAL_AUTH_ACTION_STATE: AuthActionState = {
  status: "idle",
  message: "",
};

export function SignupForm() {
  const router = useRouter();
  const [state, formAction] = useFormState(signupAction, INITIAL_AUTH_ACTION_STATE);

  useEffect(() => {
    if (state.status === "success") {
      const timer = window.setTimeout(() => {
        router.push("/auth/login");
        router.refresh();
      }, 900);
      return () => window.clearTimeout(timer);
    }
  }, [router, state.status]);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl items-center bg-[#f7f7f4] px-4 dark:bg-slate-900">
      <div className="grid w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm md:grid-cols-2 dark:border-slate-700 dark:bg-slate-900">
        <section className="p-6 md:p-8">
          <div className="mb-4">
            <BrandMark compact />
          </div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
            Create account
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            Tạo tài khoản để bắt đầu với Baymax
          </p>

          <form action={formAction} className="mt-5 space-y-3">
            <input
              name="full_name"
              type="text"
              placeholder="Họ và tên"
              required
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
            <input
              name="email"
              type="email"
              placeholder="Email"
              required
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
            <input
              name="password"
              type="password"
              placeholder="Password (>= 6 ký tự)"
              minLength={6}
              required
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
            <AuthSubmitButton
              idleText="Sign up"
              pendingText="Signing up..."
              className="w-full rounded-lg bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-800 disabled:opacity-50 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200"
            />
            {state.message && (
              <p
                className={`text-sm ${
                  state.status === "error"
                    ? "text-red-600 dark:text-red-400"
                    : "text-emerald-700 dark:text-emerald-400"
                }`}
              >
                {state.message}
              </p>
            )}
          </form>
          <p className="mt-5 text-sm text-slate-600 dark:text-slate-300">
            Đã có tài khoản?{" "}
            <Link
              href="/auth/login"
              className="font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              Sign in
            </Link>
          </p>
        </section>

        <section className="flex items-end justify-center border-t border-[#8f1b1b] bg-[#B22222] p-0 md:border-l md:border-t-0">
          <img
            src="/brand/logo"
            alt="Baymax logo"
            className="h-auto max-h-[640px] w-full max-w-[520px] object-contain object-bottom"
          />
        </section>
      </div>
    </main>
  );
}
