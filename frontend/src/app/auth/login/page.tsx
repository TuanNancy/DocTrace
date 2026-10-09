import type { Metadata } from "next";
import { LoginForms } from "@/components/auth/LoginForms";

export const metadata: Metadata = { title: "Đăng nhập · DocTrace" };

export default function LoginPage({ searchParams }: { searchParams: { registered?: string } }) {
  return <LoginForms registered={searchParams.registered === "1"} />;
}
