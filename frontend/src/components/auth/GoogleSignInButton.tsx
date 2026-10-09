"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { GoogleLogin, GoogleOAuthProvider, useGoogleOAuth, type CredentialResponse } from "@react-oauth/google";
import { createClient } from "@/lib/supabase/client";

type Nonce = { raw: string; hashed: string };

async function createNonce(): Promise<Nonce> {
  const hex = (bytes: Uint8Array) => Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  const raw = hex(crypto.getRandomValues(new Uint8Array(32)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
  return { raw, hashed: hex(new Uint8Array(digest)) };
}

function GoogleSignIn({ scriptFailed }: { scriptFailed: boolean }) {
  const supabase = useMemo(() => createClient(), []);
  const { scriptLoadedSuccessfully } = useGoogleOAuth();
  const [nonce, setNonce] = useState<Nonce | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const inFlight = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let active = true;
    createNonce().then((value) => {
      if (active) setNonce(value);
    }).catch(() => {
      if (active) setError("Không thể chuẩn bị đăng nhập Google. Vui lòng tải lại trang.");
    });
    return () => { active = false; };
  }, [attempt]);

  const retry = (message: string) => {
    if (!mounted.current) return;
    inFlight.current = false;
    setSubmitting(false);
    setError(message);
    setNonce(null);
    setAttempt((value) => value + 1);
  };

  const signIn = async ({ credential }: CredentialResponse) => {
    if (!mounted.current || inFlight.current || !nonce) return;
    if (!credential) {
      retry("Google chưa trả về thông tin đăng nhập. Vui lòng thử lại.");
      return;
    }
    inFlight.current = true;
    setSubmitting(true);
    setError(null);
    try {
      // Google receives SHA-256(raw); Supabase validates the ID token against raw.
      // Use the shared SSR browser client so middleware receives session cookies.
      const { data, error: authError } = await supabase.auth.signInWithIdToken({
        provider: "google", token: credential, nonce: nonce.raw,
      });
      if (!mounted.current) return;
      if (authError || !data.session) {
        retry("Không thể đăng nhập bằng Google. Vui lòng thử lại.");
        return;
      }
      window.location.assign("/chat");
    } catch {
      retry("Không thể kết nối dịch vụ đăng nhập. Vui lòng thử lại.");
    }
  };

  if (scriptFailed) {
    return <p role="alert" className="text-center text-sm text-red-600">Không tải được đăng nhập Google. Vui lòng tải lại trang hoặc đăng nhập bằng email.</p>;
  }

  return (
    <div aria-busy={submitting}>
      {submitting ? (
        <p role="status" className="py-2 text-center text-sm text-slate-600 dark:text-slate-300">Đang đăng nhập…</p>
      ) : nonce && scriptLoadedSuccessfully ? (
        <GoogleLogin
          key={nonce.hashed}
          nonce={nonce.hashed}
          ux_mode="popup"
          auto_select={false}
          text="continue_with"
          width={220}
          containerProps={{ className: "flex justify-center" }}
          onSuccess={signIn}
          onError={() => retry("Google chưa hoàn tất đăng nhập. Vui lòng thử lại.")}
        />
      ) : !error && <p role="status" className="py-2 text-center text-sm text-slate-600 dark:text-slate-300">Đang tải đăng nhập Google…</p>}
      {error && <p role="alert" className="mt-3 text-center text-sm text-red-600">{error}</p>}
    </div>
  );
}

export function GoogleSignInButton() {
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim();
  const [scriptFailed, setScriptFailed] = useState(false);

  if (!clientId) {
    return <p role="status" className="text-center text-sm text-slate-600 dark:text-slate-300">Đăng nhập Google chưa được cấu hình. Bạn có thể đăng nhập bằng email.</p>;
  }

  return (
    <GoogleOAuthProvider clientId={clientId} locale="vi" onScriptLoadError={() => setScriptFailed(true)}>
      <GoogleSignIn scriptFailed={scriptFailed} />
    </GoogleOAuthProvider>
  );
}
