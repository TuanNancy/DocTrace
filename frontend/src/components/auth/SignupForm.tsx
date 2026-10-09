"use client";

import Link from "next/link";
import { useFormState } from "react-dom";
import { signupAction, type AuthActionState } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/AuthSubmitButton";
import { AuthField } from "@/components/auth/AuthField";
import { AuthShell } from "@/components/auth/AuthShell";
import styles from "./Auth.module.css";

const INITIAL_AUTH_ACTION_STATE: AuthActionState = {
  status: "idle",
  message: "",
};

export function SignupForm() {
  const [state, formAction] = useFormState(signupAction, INITIAL_AUTH_ACTION_STATE);

  return (
    <AuthShell>
      <p className={styles.formEyebrow}>BẮT ĐẦU CÙNG DOCTRACE</p>
      <h1 id="auth-heading" className={styles.formHeading}>Tạo tài khoản</h1>
      <p className={styles.formDescription}>Một nơi cho tài liệu, câu hỏi và những khám phá mới của bạn.</p>

      <form action={formAction} className={styles.form}>
        <AuthField name="full_name" label="Họ và tên" placeholder="Tên của bạn" autoComplete="name" />
        <AuthField name="email" label="Địa chỉ email" placeholder="ban@vidu.com" autoComplete="email" />
        <AuthField name="password" label="Mật khẩu" placeholder="Tạo mật khẩu" autoComplete="new-password" minLength={6} hint="Sử dụng ít nhất 6 ký tự cho mật khẩu." />
        {state.message && (
          <p role={state.status === "error" ? "alert" : "status"} className={`${styles.message} ${state.status === "error" ? styles.error : styles.success}`}>
            {state.message}
          </p>
        )}
        <AuthSubmitButton idleText="Tạo tài khoản" pendingText="Đang tạo tài khoản…" className={styles.submit} />
      </form>
      <p className={styles.switch}>Đã có tài khoản? <Link href="/auth/login">Đăng nhập</Link></p>
    </AuthShell>
  );
}
