import katex from "katex";
import type { InlineItem } from "@/types/blocks";

function renderInlineMath(latex: string): string {
  return katex.renderToString(latex, {
    throwOnError: false,
    displayMode: false,
    output: "html",
    strict: "ignore",
  });
}

function InlineNode({ item, keyPath }: { item: InlineItem; keyPath: string }) {
  if (item.type === "text") {
    const s = item.styles ?? {};
    let node: React.ReactNode = item.text;
    if (s.code) {
      node = (
        <code className="rounded-[3px] border border-[#ffffff12] bg-[#1a1a1b] px-1.5 py-0.5 font-mono text-[0.85em] text-[#e8e8e8]">
          {node}
        </code>
      );
    }
    if (s.italic) node = <em className="italic text-[#e8e8e8]">{node}</em>;
    if (s.bold) node = <strong className="font-semibold text-[#f0f0f0]">{node}</strong>;
    return <>{node}</>;
  }
  if (item.type === "math") {
    return (
      <span
        className="katex-inline text-[#e8e8e8]"
        dangerouslySetInnerHTML={{ __html: renderInlineMath(item.props.latex) }}
      />
    );
  }
  return (
    <a
      href={item.href}
      className="text-[#e8e8e8] underline decoration-[#d2d2d244] underline-offset-[3px] transition-colors hover:text-white hover:decoration-[#d2d2d288]"
      target={item.href.startsWith("http") ? "_blank" : undefined}
      rel={item.href.startsWith("http") ? "noopener noreferrer" : undefined}
    >
      {item.content.map((child, i) => (
        <InlineNode key={`${keyPath}.${i}`} item={child} keyPath={`${keyPath}.${i}`} />
      ))}
    </a>
  );
}

export function InlineContent({ items, keyPath }: { items: InlineItem[]; keyPath: string }) {
  return (
    <>
      {items.map((item, i) => (
        <InlineNode key={`${keyPath}.${i}`} item={item} keyPath={`${keyPath}.${i}`} />
      ))}
    </>
  );
}