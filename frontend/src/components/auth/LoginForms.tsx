"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useFormState } from "react-dom";
import { useRouter } from "next/navigation";
import { loginAction } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/AuthSubmitButton";
import { BrandMark } from "@/components/BrandMark";
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
      router.replace("/chat");
      router.refresh();
    }
  }, [loginState.status, router]);

  const handleGoogleSignIn = async () => {
    setOauthLoading(true);
    setOauthError(null);

    const redirectTo = `${window.location.origin}/auth/callback?next=/chat`;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo,
        queryParams: { prompt: "select_account" },
      },
    });

    if (error) {
      setOauthError(error.message);
      setOauthLoading(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl items-center bg-[#f7f7f4] px-4 dark:bg-slate-900">
      <div className="grid w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm md:grid-cols-2 dark:border-slate-700 dark:bg-slate-900">
        <section className="p-6 md:p-8">
          <div className="mb-4">
            <BrandMark compact />
          </div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
            Welcome back
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            Đăng nhập để tiếp tục vào Baymax
          </p>

          <form action={loginFormAction} className="mt-5 space-y-3">
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
              idleText="Login"
              pendingText="Signing in..."
              className="w-full rounded-lg bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-800 disabled:opacity-50 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200"
            />
          </form>

          <div className="my-4 text-center text-sm text-slate-500 dark:text-slate-400">
            Or continue with
          </div>
          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={oauthLoading}
            className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2 font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            {oauthLoading ? "Redirecting to Google..." : "Continue with Google"}
          </button>

          {(oauthError || loginState.message) && (
            <p
              className={`mt-3 text-sm ${
                (oauthError || loginState.status === "error")
                  ? "text-red-600 dark:text-red-400"
                  : "text-emerald-700 dark:text-emerald-400"
              }`}
            >
              {oauthError || loginState.message}
            </p>
          )}

          <p className="mt-5 text-sm text-slate-600 dark:text-slate-300">
            Chưa có tài khoản?{" "}
            <Link
              href="/auth/signup"
              className="font-medium text-blue-600 hover:underline dark:text-blue-400"
            >
              Sign up
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
