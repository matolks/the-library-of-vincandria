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
    <div className="flex gap-12 py-12">
      <aside className="sticky top-12 hidden h-[calc(100vh-6rem)] w-64 shrink-0 flex-col pl-8 lg:flex">
        <div className="shrink-0">
          <p className="mb-6 font-mono text-[10px] font-light uppercase tracking-[0.3em] text-[#d2d2d266]">
            Topics
          </p>
          <div className="mb-4 h-px w-8 bg-[#d2d2d233]" />
        </div>
        <div className="scrollbar-hover min-h-0 flex-1 overflow-y-auto">
          <TopicSidebar basePath={`/${group}/${course}`} topics={courseRecord.topics} />
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-10"><div className="mx-auto max-w-[900px]">{children}</div></main>
    </div>
  );
}