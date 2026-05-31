import Link from "next/link";
import { notFound } from "next/navigation";
import "katex/dist/katex.min.css";

import { prisma } from "@/app/lib/prisma";
import { BlockRenderer } from "@/app/components/BlockRenderer";
import type { Block } from "@/types/blocks";

interface PageProps {
  params: Promise<{ group: string; course: string; topic: string }>;
}

interface CitationItem {
  key: string;
  label: string;
  href?: string;
}

export default async function TopicPage({ params }: PageProps) {
  const { group, course, topic } = await params;

  const topicRecord = await prisma.topic.findFirst({
    where: {
      slug: topic,
      course: { slug: course },
      groups: { some: { slug: group } },
    },
    include: {
      blocks: { orderBy: { order: "asc" } },
      course: true,
    },
  });

  if (!topicRecord) notFound();

  const siblings = await prisma.topic.findMany({
    where: {
      course: { slug: course },
      groups: { some: { slug: group } },
    },
    orderBy: { order: "asc" },
    select: { slug: true, title: true },
  });
  const currentIdx = siblings.findIndex((s) => s.slug === topic);
  const prev = currentIdx > 0 ? siblings[currentIdx - 1] : null;
  const next =
    currentIdx >= 0 && currentIdx < siblings.length - 1
      ? siblings[currentIdx + 1]
      : null;

  // ASSUMPTION: Block.content JSON stores `{ content: InlineItem[]|[], props: {...} }`.
  const blocks: Block[] = topicRecord.blocks.map((row) => {
    const payload = row.content as { content: unknown; props?: unknown };
    return {
      id: row.id,
      type: row.type,
      content: payload.content,
      props: payload.props ?? {},
      generation_metadata: row.generation_metadata ?? null,
    } as Block;
  });

  const citationChunkIds = collectSourceChunkIds(blocks);
  const chunks = citationChunkIds.length
    ? await prisma.chunk.findMany({
        where: {
          id: { in: citationChunkIds },
          courseId: topicRecord.courseId,
        },
        select: {
          id: true,
          sourcePath: true,
          sourceType: true,
          pageNumber: true,
          sectionPath: true,
        },
      })
    : [];
  const citations = buildCitationItems(citationChunkIds, chunks);

  return (
    <article className="max-w-[860px]">
      <Link
        href={`/${group}/${course}`}
        className="mb-6 inline-block font-mono text-[12px] font-light uppercase tracking-[0.4em] text-[#d2d2d266] transition-colors hover:text-[#d2d2d2]"
      >
        ← {topicRecord.course.name}
      </Link>

      <h1 className="mb-4 font-serif font-medium leading-[1.05] tracking-tight text-[#f0f0f0] text-[clamp(2rem,5vw,3.5rem)]">
        {topicRecord.title}
      </h1>

      {topicRecord.summary && (
        <p className="mb-10 max-w-[600px] text-[15px] font-light leading-relaxed text-[#d2d2d299]">
          {topicRecord.summary}
        </p>
      )}

      <div className="mb-8 h-px w-12 bg-[#d2d2d233]" />

      <BlockRenderer blocks={blocks} />

      <CitationFooter citations={citations} />

      {(prev || next) && (
        <nav className="mt-20 grid grid-cols-2 gap-4 border-t border-[#ffffff18] pt-8">
          {prev ? (
            <Link
              href={`/${group}/${course}/${prev.slug}`}
              className="group flex flex-col gap-1.5 rounded-[6px] border border-[#ffffff18] bg-[#111112] px-5 py-4 no-underline transition-colors hover:bg-[#1a1a1b]"
            >
              <span className="font-mono text-[10px] font-light uppercase tracking-[0.3em] text-[#d2d2d266]">
                ← Previous
              </span>
              <span className="font-serif text-[15px] font-medium text-[#e8e8e8] transition-colors group-hover:text-white">
                {prev.title}
              </span>
            </Link>
          ) : (
            <div />
          )}
          {next ? (
            <Link
              href={`/${group}/${course}/${next.slug}`}
              className="group flex flex-col items-end gap-1.5 rounded-[6px] border border-[#ffffff18] bg-[#111112] px-5 py-4 text-right no-underline transition-colors hover:bg-[#1a1a1b]"
            >
              <span className="font-mono text-[10px] font-light uppercase tracking-[0.3em] text-[#d2d2d266]">
                Next →
              </span>
              <span className="font-serif text-[15px] font-medium text-[#e8e8e8] transition-colors group-hover:text-white">
                {next.title}
              </span>
            </Link>
          ) : (
            <div />
          )}
        </nav>
      )}
    </article>
  );
}

function collectSourceChunkIds(blocks: Block[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const block of blocks) {
    const ids = block.generation_metadata?.source_chunk_ids;
    if (!Array.isArray(ids)) continue;
    for (const id of ids) {
      if (typeof id !== "string" || seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

function buildCitationItems(
  orderedIds: string[],
  chunks: Array<{
    id: string;
    sourcePath: string;
    sourceType: string;
    pageNumber: number | null;
    sectionPath: string | null;
  }>
): CitationItem[] {
  const byId = new Map(chunks.map((chunk) => [chunk.id, chunk]));
  const seen = new Set<string>();
  const out: CitationItem[] = [];
  for (const id of orderedIds) {
    const chunk = byId.get(id);
    if (!chunk) continue;
    const key = [
      chunk.sourcePath,
      chunk.pageNumber ?? "",
      chunk.sectionPath ?? "",
    ].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      key,
      ...formatCitation(chunk),
    });
  }
  return out;
}

function formatCitation(chunk: {
  sourcePath: string;
  sourceType: string;
  pageNumber: number | null;
  sectionPath: string | null;
}): { label: string; href?: string } {
  const isWeb = chunk.sourceType === "web" || /^https?:\/\//.test(chunk.sourcePath);
  const page = chunk.pageNumber ? `, p. ${chunk.pageNumber}` : "";
  const section = chunk.sectionPath ? `, ${chunk.sectionPath}` : "";
  if (isWeb) {
    const url = /^https?:\/\//.test(chunk.sourcePath) ? chunk.sourcePath : undefined;
    const label = url ? domainLabel(url) : chunk.sourcePath;
    return { label: `${label}${section}${page}`, href: url };
  }
  return { label: `${basename(chunk.sourcePath)}${section}${page}` };
}

function domainLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function basename(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

function CitationFooter({ citations }: { citations: CitationItem[] }) {
  if (!citations.length) return null;

  return (
    <section className="mt-16 border-t border-[#ffffff18] pt-6">
      <h2 className="mb-3 font-mono text-[10px] font-light uppercase tracking-[0.35em] text-[#d2d2d266]">
        Sources
      </h2>
      <ol className="space-y-1.5 pl-5 text-[12px] font-light leading-relaxed text-[#d2d2d280]">
        {citations.map((citation) => (
          <li key={citation.key} className="pl-1">
            {citation.href ? (
              <a
                href={citation.href}
                className="underline decoration-[#d2d2d244] underline-offset-4 transition-colors hover:text-[#e8e8e8]"
              >
                {citation.label}
              </a>
            ) : (
              citation.label
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
