"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { compile, type EvalFunction } from "mathjs";
import type { PlotBlock } from "@/types/blocks";

const Plot = dynamic(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => (
    <div className="my-6 h-[320px] animate-pulse rounded-[4px] border border-[#ffffff18] bg-[#0a0a0b]" />
  ),
});

// ---- shared layout ------------------------------------------------------

const BASE_FONT = {
  color: "#d2d2d2",
  family: "ui-monospace, SFMono-Regular, Menlo, monospace",
  size: 11,
};

const AXIS_2D = {
  gridcolor: "#ffffff14",
  zerolinecolor: "#ffffff33",
  linecolor: "#ffffff33",
  tickcolor: "#ffffff33",
};

const AXIS_3D = {
  gridcolor: "#ffffff14",
  zerolinecolor: "#ffffff33",
  linecolor: "#ffffff33",
  backgroundcolor: "rgba(0,0,0,0)",
  color: "#d2d2d2",
};

const SURFACE_COLORSCALE: [number, string][] = [
  [0, "#1e3a5f"],
  [0.5, "#5a7ab5"],
  [1, "#a8c5ff"],
];

const LINE_COLORS = ["#a8c5ff", "#f0cf85", "#f09b9b", "#9bbdff", "#d4b3f0"];

// ---- helpers ------------------------------------------------------------

function linspace(lo: number, hi: number, n: number): number[] {
  if (n <= 1) return [lo];
  const step = (hi - lo) / (n - 1);
  return Array.from({ length: n }, (_, i) => lo + i * step);
}

// Tolerate JS-Math-style expressions from the model.
// mathjs has sqrt/sin/cos/min/max/pow/abs/exp/log as bare names, and PI/E
// as constants, so stripping `Math.` is a safe normalization. Also normalize
// `**` to `^` for exponentiation.
function normalizeExpression(expr: string): string {
  return expr.replace(/Math\./g, "").replace(/\*\*/g, "^");
}

function safeCompile(expr: string): EvalFunction | null {
  try {
    return compile(normalizeExpression(expr));
  } catch {
    return null;
  }
}

// ---- main dispatch ------------------------------------------------------

export function PlotRenderer({ block }: { block: PlotBlock }) {
  switch (block.props.kind) {
    case "function2d":
      return <Function2D block={block} />;
    case "surface3d":
      return <Surface3D block={block} />;
    default:
      return (
        <SpecPreview
          block={block}
          note={`renderer not yet implemented for ${block.props.kind}`}
        />
      );
  }
}

// ---- function2d ---------------------------------------------------------

function Function2D({ block }: { block: PlotBlock }) {
  const { expression, domain, labels } = block.props;
  const exprs = Array.isArray(expression) ? expression : [expression];

  const traces = useMemo(() => {
    const xr = domain.x;
    if (!xr) return null;
    const xs = linspace(xr[0], xr[1], 200);
    const out: unknown[] = [];
    for (let i = 0; i < exprs.length; i++) {
      const fn = safeCompile(exprs[i]);
      if (!fn) return null;
      try {
        const ys = xs.map((x) => {
          const v = Number(fn.evaluate({ x }));
          return Number.isFinite(v) ? v : null;
        });
        out.push({
          x: xs,
          y: ys,
          type: "scatter",
          mode: "lines",
          name: exprs[i],
          line: { color: LINE_COLORS[i % LINE_COLORS.length], width: 2 },
          hovertemplate: "x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>",
        });
      } catch {
        return null;
      }
    }
    return out;
  }, [exprs, domain.x]);

  if (!traces) {
    return <SpecPreview block={block} note="couldn't evaluate expression" />;
  }

  return (
    <PlotFigure title={labels?.title}>
      <Plot
        data={traces as never[]}
        layout={{
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          font: BASE_FONT,
          margin: { l: 50, r: 20, t: 20, b: 45 },
          height: 320,
          autosize: true,
          xaxis: { ...AXIS_2D, title: { text: labels?.x ?? "x" } },
          yaxis: { ...AXIS_2D, title: { text: labels?.y ?? "y" } },
          showlegend: exprs.length > 1,
          legend: { font: BASE_FONT, bgcolor: "rgba(0,0,0,0)" },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false, responsive: true }}
      />
    </PlotFigure>
  );
}

// ---- surface3d ----------------------------------------------------------

function Surface3D({ block }: { block: PlotBlock }) {
  const { expression, domain, labels } = block.props;
  const exprs = Array.isArray(expression) ? expression : [expression];

  const traces = useMemo(() => {
    if (!domain.x || !domain.y) return null;
    const N = 50;
    const xs = linspace(domain.x[0], domain.x[1], N);
    const ys = linspace(domain.y[0], domain.y[1], N);
    const out: unknown[] = [];
    for (const e of exprs) {
      const fn = safeCompile(e);
      if (!fn) return null;
      try {
        const z: (number | null)[][] = [];
        for (let i = 0; i < N; i++) {
          const row: (number | null)[] = [];
          for (let j = 0; j < N; j++) {
            const v = Number(fn.evaluate({ x: xs[j], y: ys[i] }));
            row.push(Number.isFinite(v) ? v : null);
          }
          z.push(row);
        }
        out.push({
          x: xs,
          y: ys,
          z,
          type: "surface",
          colorscale: SURFACE_COLORSCALE,
          showscale: false,
          contours: { z: { show: false } },
          hovertemplate: "x=%{x:.2f}<br>y=%{y:.2f}<br>z=%{z:.2f}<extra></extra>",
        });
      } catch {
        return null;
      }
    }
    return out;
  }, [exprs, domain.x, domain.y]);

  if (!traces) {
    return <SpecPreview block={block} note="couldn't evaluate expression" />;
  }

  return (
    <PlotFigure title={labels?.title}>
      <Plot
        data={traces as never[]}
        layout={{
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          font: BASE_FONT,
          margin: { l: 0, r: 0, t: 10, b: 0 },
          height: 480,
          autosize: true,
          scene: {
            xaxis: { ...AXIS_3D, title: { text: labels?.x ?? "x" } },
            yaxis: { ...AXIS_3D, title: { text: labels?.y ?? "y" } },
            zaxis: { ...AXIS_3D, title: { text: labels?.z ?? "z" } },
            camera: { eye: { x: 1.6, y: 1.6, z: 1.1 } },
          },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false, responsive: true }}
      />
    </PlotFigure>
  );
}

// ---- shared figure shell ------------------------------------------------

function PlotFigure({
  children,
  title,
}: {
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <figure className="my-6 overflow-hidden rounded-[4px] border border-[#ffffff18] bg-[#0a0a0b]">
      {children}
      {title && (
        <figcaption className="border-t border-[#ffffff0a] px-4 py-2 text-center font-serif text-[13px] text-[#d2d2d2]">
          {title}
        </figcaption>
      )}
    </figure>
  );
}

// ---- spec preview (fallback for unimplemented kinds and errors) --------

function SpecPreview({ block, note }: { block: PlotBlock; note?: string }) {
  const { kind, expression, domain, labels } = block.props;
  const exprs = Array.isArray(expression) ? expression : [expression];
  const domainStr = Object.entries(domain)
    .map(([k, v]) => `${k} ∈ [${v?.[0]}, ${v?.[1]}]`)
    .join(", ");

  return (
    <figure className="my-6 rounded-[4px] border border-dashed border-[#ffffff18] bg-[#111112] p-5">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <span className="font-mono text-[10px] font-light uppercase tracking-[0.25em] text-[#d2d2d255]">
          Plot · {kind}
        </span>
        {note && (
          <span className="font-mono text-[10px] font-light text-[#e57c7c99]">
            {note}
          </span>
        )}
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