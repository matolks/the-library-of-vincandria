import { notFound } from "next/navigation";
import "katex/dist/katex.min.css";
import Link from "next/link";
import { prisma } from "@/app/lib/prisma";
import { BlockRenderer } from "@/app/components/BlockRenderer";
import type { Block } from "@/types/blocks";

interface PageProps {
  params: Promise<{ group: string; course: string; topic: string }>;
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

  return (
    <article className="max-w-[860px]">
      <Link
        href={`/${group}/${course}`}
        className="mb-6 inline-block font-mono text-[10px] font-light uppercase tracking-[0.4em] text-[#d2d2d266] transition-colors hover:text-[#d2d2d2]"
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
    </article>
  );
}