import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";
import { getSupabaseConfig } from "./config";

export async function createClient() {
  const cookieStore = await cookies();
  const { url, key } = getSupabaseConfig();
  return createServerClient(url, key, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll(cookiesToSet) {
        // This helper is used in Server Actions and Route Handlers (writable cookies).
        cookiesToSet.forEach(({ name, value, options }) => {
          cookieStore.set(name, value, options);
        });
      },
    },
  });
}

/** Stage signup cookies so a failed PKCE signup does not reset the form. */
export async function createSignupClient() {
  const cookieStore = await cookies();
  const { url, key } = getSupabaseConfig();
  const pending = new Map<string, { name: string; value: string; options: CookieOptions }>();
  const client = createServerClient(url, key, {
    cookies: {
      getAll() {
        const merged = new Map(cookieStore.getAll().map((cookie) => [cookie.name, cookie]));
        pending.forEach((cookie, name) => merged.set(name, cookie));
        return Array.from(merged.values());
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach((cookie) => pending.set(cookie.name, cookie));
      },
    },
  });
  return {
    client,
    commitCookies() {
      pending.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
    },
  };
}
