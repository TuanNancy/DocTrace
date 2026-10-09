"use client";

import Link from "next/link";
import { useFormState } from "react-dom";
import { loginAction, type AuthActionState } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/AuthSubmitButton";
import { AuthField } from "@/components/auth/AuthField";
import { AuthShell } from "@/components/auth/AuthShell";
import { GoogleSignInButton } from "@/components/auth/GoogleSignInButton";
import styles from "./Auth.module.css";

const INITIAL_AUTH_ACTION_STATE: AuthActionState = {
  status: "idle",
  message: "",
};

export function LoginForms({ registered = false }: { registered?: boolean }) {
  const [loginState, loginFormAction] = useFormState(
    loginAction,
    INITIAL_AUTH_ACTION_STATE
  );

  return (
    <AuthShell>
      <p className={styles.formEyebrow}>KHÔNG GIAN CỦA BẠN</p>
      <h1 id="auth-heading" className={styles.formHeading}>Chào mừng trở lại</h1>
      <p className={styles.formDescription}>Đăng nhập để tiếp tục khám phá tài liệu cùng DocTrace.</p>

      <form action={loginFormAction} className={styles.form}>
        {registered && (
          <p role="status" className={`${styles.message} ${styles.success}`}>
            Tạo tài khoản thành công. Nếu nhận được email xác nhận, hãy mở liên kết trong email trước khi đăng nhập.
          </p>
        )}
        <AuthField name="email" label="Địa chỉ email" placeholder="ban@vidu.com" autoComplete="email" />
        <AuthField name="password" label="Mật khẩu" placeholder="Nhập mật khẩu" autoComplete="current-password" />
        {loginState.message && (
          <p role={loginState.status === "error" ? "alert" : "status"} className={`${styles.message} ${loginState.status === "error" ? styles.error : styles.success}`}>
            {loginState.message}
          </p>
        )}
        <AuthSubmitButton idleText="Đăng nhập" pendingText="Đang đăng nhập…" className={styles.submit} />
      </form>

      <div className={styles.divider}>hoặc tiếp tục với</div>
      <div className={styles.google}><GoogleSignInButton /></div>
      <p className={styles.switch}>Chưa có tài khoản? <Link href="/auth/signup">Đăng ký ngay</Link></p>
    </AuthShell>
  );
}
