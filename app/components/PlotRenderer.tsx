"use client";

import type { PlotBlock } from "@/types/blocks";

export function PlotRenderer({ block }: { block: PlotBlock }) {
  const { kind, expression, domain, labels } = block.props;
  const exprs = Array.isArray(expression) ? expression : [expression];
  const domainStr = Object.entries(domain)
    .map(([k, v]) => `${k} ∈ [${v?.[0]}, ${v?.[1]}]`)
    .join(", ");

  return (
    <figure className="my-6 rounded-[4px] border border-dashed border-[#ffffff18] bg-[#111112] p-5">
      <div className="mb-2 font-mono text-[10px] font-light uppercase tracking-[0.25em] text-[#d2d2d255]">
        Plot · {kind}
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-[#e8e8e8]">
        {exprs.join("\n")}
      </pre>
      {domainStr && (
        <div className="mt-2 font-mono text-[11px] text-[#d2d2d266]">{domainStr}</div>
      )}
      {labels?.title && (
        <figcaption className="mt-2 font-serif text-[14px] text-[#d2d2d2]">
          {labels.title}
        </figcaption>
      )}
    </figure>
  );
}