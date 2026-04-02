"use client";

interface BrandMarkProps {
  compact?: boolean;
  refreshOnClick?: boolean;
  /** Chữ trắng cho nền sidebar tối */
  variant?: "default" | "onDark";
}

export function BrandMark({
  compact = false,
  refreshOnClick = false,
  variant = "default",
}: BrandMarkProps) {
  const imageClass = compact
    ? "h-8 w-8 rounded-md object-contain"
    : "h-10 w-10 rounded-md object-contain";
  const textClass =
    variant === "onDark"
      ? compact
        ? "text-base font-semibold text-white"
        : "text-lg font-semibold text-white"
      : compact
        ? "text-base font-semibold text-slate-800 dark:text-slate-100"
        : "text-lg font-semibold text-slate-800 dark:text-slate-100";

  if (refreshOnClick) {
    return (
      <button
        type="button"
        aria-label="Refresh page"
        onClick={() => window.location.reload()}
        className={`inline-flex items-center gap-2 rounded-lg px-2 py-1 transition-colors ${
          variant === "onDark"
            ? "hover:bg-white/10"
            : "hover:bg-slate-100/70 dark:hover:bg-white/10"
        }`}
      >
        <img src="/brand/logo" alt="Baymax logo" className={imageClass} />
        <span className={textClass}>Baymax</span>
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <img src="/brand/logo" alt="Baymax logo" className={imageClass} />
      <span className={textClass}>Baymax</span>
    </div>
  );
}
