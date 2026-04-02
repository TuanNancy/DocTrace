"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useFormState } from "react-dom";
import { signupAction } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/AuthSubmitButton";

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
  }, [router, state.message, state.status]);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-4">
      <div className="w-full rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800/50">
        <h1 className="mb-4 text-xl font-semibold text-slate-800 dark:text-slate-100">
          Sign up
        </h1>
        <form action={formAction} className="space-y-3">
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
            className="w-full rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
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
        <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">
          Đã có tài khoản?{" "}
          <Link
            href="/auth/login"
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
