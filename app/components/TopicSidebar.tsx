"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface Topic {
  id: string;
  slug: string;
  title: string;
  order: number;
}

export function TopicSidebar({
  basePath,
  topics,
}: {
  basePath: string;
  topics: Topic[];
}) {
  const pathname = usePathname();

  return (
    <ol className="space-y-0.5">
      {topics.map((t, idx) => {
        const href = `${basePath}/${t.slug}`;
        const active = pathname === href;
        return (
          <li key={t.id}>
            <Link
              href={href}
              className={[
                "flex items-baseline gap-3 rounded-[3px] px-2 py-1.5 text-[13px] font-light leading-snug transition-colors",
                active
                  ? "bg-[#1a1a1b] text-[#f0f0f0]"
                  : "text-[#d2d2d299] hover:bg-[#111112] hover:text-[#e8e8e8]",
              ].join(" ")}
            >
              <span
                className={[
                  "font-mono text-[10px] tabular-nums",
                  active ? "text-[#d2d2d266]" : "text-[#d2d2d244]",
                ].join(" ")}
              >
                {String(idx + 1).padStart(2, "0")}
              </span>
              <span>{t.title}</span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}