import { createBrowserClient } from "@supabase/ssr";
import { getSupabaseConfig } from "./supabase-config";

export function createClient() {
  const { url, key } = getSupabaseConfig();
  // The SDK manages the browser singleton; never share server clients.
  return createBrowserClient(url, key);
}
