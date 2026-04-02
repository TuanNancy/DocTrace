import { readFile } from "node:fs/promises";
import path from "node:path";

function getCandidatePaths(): string[] {
  const cwd = process.cwd();

  return [
    // Use only logo1.png to avoid stale old-logo fallback.
    path.resolve(cwd, "logo1.png"),
    path.resolve(cwd, "public", "logo1.png"),
    path.resolve(cwd, "..", "logo1.png"),
  ].filter(Boolean);
}

export async function GET() {
  for (const candidate of getCandidatePaths()) {
    try {
      const file = await readFile(candidate);
      return new Response(file, {
        status: 200,
        headers: {
          "Content-Type": "image/png",
          "Cache-Control": "no-store",
        },
      });
    } catch {
      // Try next candidate path.
    }
  }

  return new Response("Logo not found", { status: 404 });
}
