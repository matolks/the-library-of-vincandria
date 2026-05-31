import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/app/lib/prisma";

interface PageProps {
  params: Promise<{ group: string }>;
}

export default async function GroupPage({ params }: PageProps) {
  const { group } = await params;

  const groupRecord = await prisma.topicGroup.findUnique({
    where: { slug: group },
    include: {
      topics: {
        include: { course: true },
        orderBy: [{ course: { slug: "asc" } }, { order: "asc" }],
      },
    },
  });

  if (!groupRecord) notFound();

  const courseMap = new Map<
    string,
    { id: string; slug: string; name: string; topicCount: number }
  >();
  for (const t of groupRecord.topics) {
    const existing = courseMap.get(t.course.id);
    if (existing) existing.topicCount += 1;
    else
      courseMap.set(t.course.id, {
        id: t.course.id,
        slug: t.course.slug,
        name: t.course.name,
        topicCount: 1,
      });
  }
  const courses = Array.from(courseMap.values());

  return (
    <section className="mx-auto max-w-[1100px] px-10 py-20">
      <p className="mb-8 font-mono text-[10px] font-light uppercase tracking-[0.4em] text-[#d2d2d266]">
        <Link href="/" className="transition-colors hover:text-[#d2d2d2]">
          The Library of Vincandria
        </Link>
      </p>

      <h1 className="mb-5 max-w-[880px] font-serif font-medium leading-[1.05] tracking-tight text-[#f0f0f0] text-[clamp(2.5rem,6vw,5rem)]">
        {groupRecord.name}
      </h1>

      {groupRecord.description && (
        <p className="mb-20 max-w-[520px] text-[15px] font-light leading-relaxed text-[#d2d2d299]">
          {groupRecord.description}
        </p>
      )}

      <div className="mb-10 h-px w-12 bg-[#d2d2d233]" />

      <div className="overflow-hidden rounded-[6px] border border-[#ffffff18]">
        {courses.map((c, idx) => (
          <Link
            key={c.id}
            href={`/${group}/${c.slug}`}
            className="group grid grid-cols-[1fr_auto] items-center gap-4 border-b border-[#ffffff12] bg-[#111112] px-8 py-6 no-underline transition-colors last:border-b-0 hover:bg-[#1a1a1b]"
          >
            <div className="flex items-baseline gap-6">
              <span className="min-w-[24px] font-mono text-[11px] font-light text-[#d2d2d244]">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <div>
                <p className="mb-2 font-serif text-[1.3rem] font-medium text-[#e8e8e8] transition-colors group-hover:text-white">
                  {c.name}
                </p>
                <span className="rounded-[2px] border border-[#d2d2d21a] px-1.5 py-0.5 font-mono text-[10px] font-light tracking-[0.06em] text-[#d2d2d255]">
                  {c.topicCount} topic{c.topicCount === 1 ? "" : "s"}
                </span>
              </div>
            </div>
            <span className="-translate-x-1.5 text-lg text-[#d2d2d266] opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100">
              →
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}