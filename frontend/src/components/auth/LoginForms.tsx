"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useFormState } from "react-dom";
import { loginAction } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/AuthSubmitButton";
import { createClient } from "@/lib/client";

type AuthActionState = {
  status: "idle" | "success" | "error";
  message: string;
};

const INITIAL_AUTH_ACTION_STATE: AuthActionState = {
  status: "idle",
  message: "",
};

export function LoginForms() {
  const router = useRouter();
  const supabase = useMemo(() => createClient(), []);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [loginState, loginFormAction] = useFormState(
    loginAction,
    INITIAL_AUTH_ACTION_STATE
  );

  useEffect(() => {
    if (loginState.status === "success") {
      router.replace("/");
      router.refresh();
    }
  }, [loginState.status, router]);

  const handleGoogleSignIn = async () => {
    setOauthLoading(true);
    setOauthError(null);

    const redirectTo = `${window.location.origin}/auth/callback?next=/`;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo },
    });

    if (error) {
      setOauthError(error.message);
      setOauthLoading(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-4">
      <div className="w-full rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800/50">
        <h1 className="mb-4 text-xl font-semibold text-slate-800 dark:text-slate-100">
          Sign in
        </h1>

        <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={oauthLoading}
          className="mb-4 w-full rounded-lg border border-slate-300 bg-white px-4 py-2 font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          {oauthLoading ? "Redirecting to Google..." : "Sign in with Google"}
        </button>
        {oauthError && (
          <p className="mb-4 text-sm text-red-600 dark:text-red-400">{oauthError}</p>
        )}

        <form action={loginFormAction} className="space-y-3">
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
            placeholder="Password"
            required
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          />
          <AuthSubmitButton
            idleText="Sign in"
            pendingText="Signing in..."
            className="w-full rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-600"
          />
          {loginState.message && (
            <p
              className={`text-sm ${
                loginState.status === "error"
                  ? "text-red-600 dark:text-red-400"
                  : "text-emerald-700 dark:text-emerald-400"
              }`}
            >
              {loginState.message}
            </p>
          )}
        </form>

        <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">
          Chưa có tài khoản?{" "}
          <Link
            href="/auth/signup"
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            Sign up
          </Link>
        </p>
      </div>
    </main>
  );
}
