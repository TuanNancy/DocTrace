import { createBrowserClient } from "@supabase/ssr";
import { getSupabaseConfig } from "./supabase-config";

export function createClient() {
  const { url, key } = getSupabaseConfig();
  // createBrowserClient manages its browser singleton; never share server clients.
  return createBrowserClient(url, key);
}
