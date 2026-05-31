import katex from "katex";
import type { Block, HeadingLevel } from "@/types/blocks";
import { InlineContent } from "./InlineContent";
import { PlotRenderer } from "./PlotRenderer";

function renderDisplayMath(latex: string): string {
  return katex.renderToString(latex, {
    throwOnError: false,
    displayMode: true,
    output: "html",
    strict: "ignore",
  });
}

// Callout palette: low-saturation tints on the dark canvas.
const CALLOUT_STYLES: Record<string, { wrap: string; label: string }> = {
  note: {
    wrap: "border-l-2 border-l-[#7aa7ff80] bg-[#7aa7ff0d]",
    label: "text-[#9bbdff]",
  },
  insight: {
    wrap: "border-l-2 border-l-[#e5b85c80] bg-[#e5b85c0d]",
    label: "text-[#f0cf85]",
  },
  warning: {
    wrap: "border-l-2 border-l-[#e57c7c80] bg-[#e57c7c0d]",
    label: "text-[#f09b9b]",
  },
};

const CALLOUT_LABEL: Record<string, string> = {
  note: "Note",
  insight: "Insight",
  warning: "Warning",
};

function HeadingTag({ level, children }: { level: HeadingLevel; children: React.ReactNode }) {
  // Block heading levels start at h2 (page title owns h1).
  const cls = {
    1: "mt-12 mb-4 font-serif text-[1.75rem] font-medium leading-tight tracking-tight text-[#f0f0f0]",
    2: "mt-10 mb-3 font-serif text-[1.35rem] font-medium leading-tight tracking-tight text-[#f0f0f0]",
    3: "mt-8 mb-2 font-serif text-[1.1rem] font-medium leading-snug text-[#e8e8e8]",
  }[level];
  const Tag = (`h${level + 1}` as "h2" | "h3" | "h4");
  return <Tag className={cls}>{children}</Tag>;
}

function renderSingleBlock(block: Block): React.ReactNode {
  switch (block.type) {
    case "paragraph":
      return (
        <p className="my-4 text-[15px] font-light leading-[1.75] text-[#d2d2d2]">
          <InlineContent items={block.content} keyPath={block.id} />
        </p>
      );

    case "heading":
      return (
        <HeadingTag level={block.props.level}>
          <InlineContent items={block.content} keyPath={block.id} />
        </HeadingTag>
      );

    case "codeBlock": {
      const lang = block.props.language;
      return (
        <div className="my-6 overflow-hidden rounded-[4px] border border-[#ffffff12] bg-[#0a0a0b]">
          <div className="border-b border-[#ffffff0a] px-4 py-1.5 font-mono text-[10px] font-light uppercase tracking-[0.2em] text-[#d2d2d255]">
            {lang}
          </div>
          <pre className="overflow-x-auto px-4 py-4 font-mono text-[13px] leading-relaxed text-[#e8e8e8]">
            <code className={`language-${lang}`}>{block.content[0].text}</code>
          </pre>
        </div>
      );
    }

    case "callout": {
      const variant = block.props.variant;
      const styles = CALLOUT_STYLES[variant];
      return (
        <aside className={`my-6 rounded-[3px] px-5 py-4 ${styles.wrap}`}>
          <div className={`mb-1.5 font-mono text-[10px] font-light uppercase tracking-[0.25em] ${styles.label}`}>
            {CALLOUT_LABEL[variant]}
          </div>
          <div className="text-[14.5px] font-light leading-relaxed text-[#d2d2d2]">
            <InlineContent items={block.content} keyPath={block.id} />
          </div>
        </aside>
      );
    }

    case "math":
      return (
        <div className="my-6 overflow-x-auto text-[#e8e8e8]">
          <div
            className="katex-display-wrap"
            dangerouslySetInnerHTML={{ __html: renderDisplayMath(block.props.latex) }}
          />
          {block.props.label && (
            <div className="mt-1 text-right font-mono text-[10px] tracking-[0.15em] text-[#d2d2d255]">
              ({block.props.label})
            </div>
          )}
        </div>
      );

    case "plot":
      return <PlotRenderer block={block} />;

    case "bulletListItem":
    case "numberedListItem":
      return null;
  }
}

export function BlockRenderer({ blocks }: { blocks: Block[] }) {
  const out: React.ReactNode[] = [];
  let i = 0;
  while (i < blocks.length) {
    const b = blocks[i];
    if (b.type === "bulletListItem" || b.type === "numberedListItem") {
      const listType = b.type;
      const group: Block[] = [];
      while (i < blocks.length && blocks[i].type === listType) {
        group.push(blocks[i]);
        i++;
      }
      const ListTag = listType === "bulletListItem" ? "ul" : "ol";
      const listCls =
        listType === "bulletListItem"
          ? "my-4 list-disc space-y-2 pl-6 marker:text-[#d2d2d244]"
          : "my-4 list-decimal space-y-2 pl-6 marker:font-mono marker:text-[#d2d2d255] marker:text-[12px]";
      out.push(
        <ListTag key={`list-${group[0].id}`} className={listCls}>
          {group.map((item) => (
            <li
              key={item.id}
              className="pl-1 text-[15px] font-light leading-[1.7] text-[#d2d2d2]"
            >
              <InlineContent
                items={(item as { content: import("@/types/blocks").InlineItem[] }).content}
                keyPath={item.id}
              />
            </li>
          ))}
        </ListTag>
      );
      continue;
    }
    out.push(<div key={b.id}>{renderSingleBlock(b)}</div>);
    i++;
  }
  return <>{out}</>;
}