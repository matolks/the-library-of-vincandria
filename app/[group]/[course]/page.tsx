import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/app/lib/prisma";

interface PageProps {
  params: Promise<{ group: string; course: string }>;
}

export default async function CoursePage({ params }: PageProps) {
  const { group, course } = await params;

  const courseRecord = await prisma.course.findUnique({
    where: { slug: course },
    include: {
      topics: {
        where: { groups: { some: { slug: group } } },
        orderBy: { order: "asc" },
        select: { id: true, slug: true, title: true, summary: true, order: true },
      },
    },
  });

  if (!courseRecord) notFound();

  return (
    <article className="max-w-[960px]">
      <Link
        href={`/${group}`}
        className="mb-6 inline-block font-mono text-[12px] font-light uppercase tracking-[0.4em] text-[#d2d2d266] transition-colors hover:text-[#d2d2d2]"
      >
        ← {group}
      </Link>

      <h1 className="mb-4 font-serif font-medium leading-[1.05] tracking-tight text-[#f0f0f0] text-[clamp(2rem,5vw,3.5rem)]">
        {courseRecord.name}
      </h1>

      <p className="mb-12 font-mono text-[12px] font-light tracking-[0.08em] text-[#d2d2d255]">
        {courseRecord.topics.length} topic{courseRecord.topics.length === 1 ? "" : "s"}
      </p>

      <div className="mb-8 h-px w-12 bg-[#d2d2d233]" />

      <div className="overflow-hidden rounded-[6px] border border-[#ffffff18]">
        {courseRecord.topics.map((t, idx) => (
          <Link
            key={t.id}
            href={`/${group}/${course}/${t.slug}`}
            className="group grid grid-cols-[1fr_auto] items-center gap-4 border-b border-[#ffffff12] bg-[#111112] px-7 py-5 no-underline transition-colors last:border-b-0 hover:bg-[#1a1a1b]"
          >
            <div className="flex items-baseline gap-5">
              <span className="min-w-[24px] font-mono text-[11px] font-light tabular-nums text-[#d2d2d244]">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <div>
                <p className="font-serif text-[1.1rem] font-medium text-[#e8e8e8] transition-colors group-hover:text-white">
                  {t.title}
                </p>
                {t.summary && (
                  <p className="mt-1.5 text-[13px] font-light leading-relaxed text-[#d2d2d299]">
                    {t.summary}
                  </p>
                )}
              </div>
            </div>
            <span className="-translate-x-1.5 text-lg text-[#d2d2d266] opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100">
              →
            </span>
          </Link>
        ))}
      </div>
    </article>
  );
}