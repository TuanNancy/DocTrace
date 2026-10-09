"use client";

import { useState } from "react";
import { Eye, EyeOff, LockKeyhole, Mail, UserRound } from "lucide-react";
import styles from "./Auth.module.css";

interface AuthFieldProps {
  name: "email" | "password" | "full_name";
  label: string;
  placeholder: string;
  autoComplete: string;
  minLength?: number;
  hint?: string;
}

export function AuthField({ name, label, placeholder, autoComplete, minLength, hint }: AuthFieldProps) {
  const [visible, setVisible] = useState(false);
  const password = name === "password";
  const Icon = password ? LockKeyhole : name === "email" ? Mail : UserRound;
  const id = `auth-${name}`;

  return (
    <div className={styles.field}>
      <label htmlFor={id}>{label}</label>
      <div className={styles.inputWrap}>
        <Icon size={17} className={styles.fieldIcon} aria-hidden="true" />
        <input
          id={id}
          name={name}
          type={password ? (visible ? "text" : "password") : name === "email" ? "email" : "text"}
          placeholder={placeholder}
          autoComplete={autoComplete}
          minLength={minLength}
          required
          aria-describedby={hint ? `${id}-hint` : undefined}
          className={password ? styles.passwordInput : undefined}
        />
        {password && (
          <button
            type="button"
            onClick={() => setVisible((value) => !value)}
            className={styles.passwordToggle}
            aria-label={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
            aria-controls={id}
          >
            {visible ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
          </button>
        )}
      </div>
      {hint && <p id={`${id}-hint`} className={styles.hint}>{hint}</p>}
    </div>
  );
}
