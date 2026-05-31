import { notFound } from "next/navigation";
import Link from "next/link";
import { prisma } from "@/app/lib/prisma";
import { TopicSidebar } from "@/app/components/TopicSidebar";

interface LayoutProps {
  params: Promise<{ group: string; course: string }>;
  children: React.ReactNode;
}

export default async function CourseLayout({ params, children }: LayoutProps) {
  const { group, course } = await params;

  const courseRecord = await prisma.course.findUnique({
    where: { slug: course },
    include: {
      topics: {
        where: { groups: { some: { slug: group } } },
        orderBy: { order: "asc" },
        select: { id: true, slug: true, title: true, order: true },
      },
    },
  });

  if (!courseRecord) notFound();

  return (
    <div className="mx-auto flex max-w-[1100px] gap-12 px-10 py-12">
      <aside className="sticky top-12 hidden h-[calc(100vh-6rem)] w-64 shrink-0 overflow-y-auto lg:block">
        <Link
          href={`/${group}`}
          className="mb-6 block font-mono text-[10px] font-light uppercase tracking-[0.3em] text-[#d2d2d266] transition-colors hover:text-[#d2d2d2]"
        >
          ← {group}
        </Link>
        <Link
          href={`/${group}/${course}`}
          className="mb-6 block font-serif text-[1.1rem] font-medium text-[#e8e8e8] transition-colors hover:text-white"
        >
          {courseRecord.name}
        </Link>
        <div className="mb-4 h-px w-8 bg-[#d2d2d233]" />
        <TopicSidebar basePath={`/${group}/${course}`} topics={courseRecord.topics} />
      </aside>
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}