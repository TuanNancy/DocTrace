"use server";

import { headers } from "next/headers";
import { createClient } from "@/lib/server";

type AuthActionState = {
  status: "idle" | "success" | "error";
  message: string;
};

function getOriginFromHeaders(value: string | null): string {
  if (!value) return "http://localhost:3000";
  const first = value.split(",")[0].trim();
  if (first.startsWith("http://") || first.startsWith("https://")) return first;
  return `https://${first}`;
}

async function resolveRedirectUrl(path: string): Promise<string> {
  const h = await headers();
  const originHeader = h.get("origin");
  const hostHeader = h.get("x-forwarded-host") ?? h.get("host");
  const envSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;
  const origin = envSiteUrl || originHeader || hostHeader || "http://localhost:3000";
  const resolvedOrigin = getOriginFromHeaders(origin);
  return `${resolvedOrigin}${path}`;
}

export async function loginAction(
  _prevState: AuthActionState,
  formData: FormData
): Promise<AuthActionState> {
  try {
    const email = String(formData.get("email") || "").trim();
    const password = String(formData.get("password") || "");

    if (!email || !password) {
      return { status: "error", message: "Email và mật khẩu là bắt buộc." };
    }

    const supabase = await createClient();
    const { error, data } = await supabase.auth.signInWithPassword({ email, password });

    if (error) {
      return { status: "error", message: error.message };
    }

    if (!data.session) {
      return {
        status: "error",
        message:
          "Đăng nhập chưa hoàn tất (không tạo được session). Vui lòng thử lại.",
      };
    }

    return { status: "success", message: "Đăng nhập thành công. Đang chuyển hướng..." };
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Đăng nhập thất bại.",
    };
  }
}

export async function signupAction(
  _prevState: AuthActionState,
  formData: FormData
): Promise<AuthActionState> {
  const fullName = String(formData.get("full_name") || "").trim();
  const email = String(formData.get("email") || "").trim();
  const password = String(formData.get("password") || "");

  if (!fullName || !email || !password) {
    return { status: "error", message: "Tên, email và mật khẩu là bắt buộc." };
  }

  if (password.length < 6) {
    return { status: "error", message: "Mật khẩu tối thiểu 6 ký tự." };
  }

  const supabase = await createClient();
  const emailRedirectTo = await resolveRedirectUrl("/auth/login");
  const { error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: { full_name: fullName },
      emailRedirectTo,
    },
  });

  if (error) {
    return { status: "error", message: error.message };
  }

  // Keep signup flow deterministic: always continue from login screen.
  await supabase.auth.signOut();

  return {
    status: "success",
    message: "Đăng ký thành công. Đang chuyển sang trang đăng nhập...",
  };
}
