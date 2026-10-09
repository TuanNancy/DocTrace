"use client";

import { useFormStatus } from "react-dom";
import { ArrowRight, LoaderCircle } from "lucide-react";

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
    <button type="submit" disabled={pending} aria-busy={pending} className={className}>
      {pending ? pendingText : idleText}
      {pending ? <LoaderCircle size={16} className="motion-safe:animate-spin" aria-hidden="true" /> : <ArrowRight size={16} aria-hidden="true" />}
    </button>
  );
}
