import { FileSearch2 } from "lucide-react";

interface BrandMarkProps {
  compact?: boolean;
  variant?: "default" | "onDark";
}

export function BrandMark({
  compact = false,
  variant = "default",
}: BrandMarkProps) {
  const iconClass = compact ? "h-8 w-8 rounded-lg" : "h-10 w-10 rounded-xl";
  const textClass =
    variant === "onDark"
      ? compact
        ? "text-base font-semibold text-white"
        : "text-lg font-semibold text-white"
      : compact
        ? "text-base font-semibold text-slate-800 dark:text-slate-100"
        : "text-lg font-semibold text-slate-800 dark:text-slate-100";

  return (
    <div className="flex items-center gap-2">
      <div className={`flex shrink-0 items-center justify-center bg-[#7546d9] text-white ${iconClass}`}>
        <FileSearch2 size={compact ? 19 : 23} strokeWidth={1.7} aria-hidden="true" />
      </div>
      <span className={textClass}>DocTrace</span>
    </div>
  );
}
