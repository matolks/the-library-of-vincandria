// Mirrors pipeline/block_schema.py. Keep in sync.

export type HeadingLevel = 1 | 2 | 3;
export type CalloutVariant = "note" | "insight" | "warning";
export type PlotKind =
  | "function2d"
  | "surface3d"
  | "levelcurves"
  | "vectorfield"
  | "parametric2d"
  | "parametric3d";

export interface InlineStyles {
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
}

export interface TextInline {
  type: "text";
  text: string;
  styles?: InlineStyles;
}

export interface MathInline {
  type: "math";
  props: { latex: string };
}

export interface LinkInline {
  type: "link";
  href: string;
  content: InlineItem[];
}

export type InlineItem = TextInline | MathInline | LinkInline;

interface BlockBase {
  id: string;
  generation_metadata?: { source_chunk_ids: string[] } | null;
}

export interface ParagraphBlock extends BlockBase {
  type: "paragraph";
  content: InlineItem[];
  props?: Record<string, never>;
}
export interface HeadingBlock extends BlockBase {
  type: "heading";
  content: InlineItem[];
  props: { level: HeadingLevel };
}
export interface BulletListItemBlock extends BlockBase {
  type: "bulletListItem";
  content: InlineItem[];
}
export interface NumberedListItemBlock extends BlockBase {
  type: "numberedListItem";
  content: InlineItem[];
}
export interface CodeBlock extends BlockBase {
  type: "codeBlock";
  content: [{ type: "text"; text: string }];
  props: { language: string };
}
export interface CalloutBlock extends BlockBase {
  type: "callout";
  content: InlineItem[];
  props: { variant: CalloutVariant };
}
export interface MathBlock extends BlockBase {
  type: "math";
  content: [];
  props: { mode: "display"; latex: string; label?: string };
}
export interface PlotBlock extends BlockBase {
  type: "plot";
  content: [];
  props: {
    kind: PlotKind;
    expression: string | string[];
    domain: Partial<Record<"x" | "y" | "z" | "t", [number, number]>>;
    labels?: Partial<Record<"x" | "y" | "z" | "title", string>>;
  };
}
export interface ImageBlock extends BlockBase {
  type: "image";
  content: [];
  props: {
    src: string;
    alt: string;
    caption?: string;
    width?: number;
  };
}

export type Block =
  | ParagraphBlock
  | HeadingBlock
  | BulletListItemBlock
  | NumberedListItemBlock
  | CodeBlock
  | CalloutBlock
  | MathBlock
  | PlotBlock
  | ImageBlock;
