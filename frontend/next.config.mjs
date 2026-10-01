import { PHASE_PRODUCTION_BUILD } from "next/constants.js";

export default function nextConfig(phase) {
  if (phase === PHASE_PRODUCTION_BUILD) {
    for (const name of ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY", "NEXT_PUBLIC_SITE_URL"]) {
      if (!process.env[name]?.trim()) throw new Error(`Missing required build variable: ${name}`);
    }
  }
  return {};
}
