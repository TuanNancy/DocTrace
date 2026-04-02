"use client";

import { useFormStatus } from "react-dom";

interface AuthSubmitButtonProps {
  idleText: string;
  pendingText: string;
  className: string;
}

export function AuthSubmitButton({
  idleText,
  pendingText,
  className,
}: AuthSubmitButtonProps) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} className={className}>
      {pending ? pendingText : idleText}
    </button>
  );
}
