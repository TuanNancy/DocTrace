"use server";

import { createClient } from "@/lib/server";

type AuthActionState = {
  status: "idle" | "success" | "error";
  message: string;
};

async function resolveRedirectUrl(path: string): Promise<string> {
  const origin = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
  return new URL(path, origin).toString();
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
  const emailRedirectTo = await resolveRedirectUrl("/auth/callback?next=/chat");
  const { data, error } = await supabase.auth.signUp({
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
  // Keep the PKCE verifier for the email callback when confirmation is required.
  if (data.session) await supabase.auth.signOut();

  return {
    status: "success",
    message: "Đăng ký thành công. Đang chuyển sang trang đăng nhập...",
  };
}
