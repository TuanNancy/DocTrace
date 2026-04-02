import { NextResponse } from "next/server";
import { createClient } from "@/lib/server";

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");

  let next = requestUrl.searchParams.get("next") ?? "/";
  if (!next.startsWith("/")) {
    next = "/";
  }

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${requestUrl.origin}${next}`);
    }
  }

  return NextResponse.redirect(
    `${requestUrl.origin}/auth/auth-code-error`
  );
}
