CREATE EXTENSION IF NOT EXISTS vector;
-- CreateEnum
CREATE TYPE "BlockSource" AS ENUM ('local', 'web', 'manual', 'generated');

-- CreateEnum
CREATE TYPE "EdgeKind" AS ENUM ('PREREQUISITE_OF');

-- CreateTable
CREATE TABLE "Block" (
    "id" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "order" INTEGER NOT NULL,
    "language" TEXT,
    "manually_edited" BOOLEAN NOT NULL DEFAULT false,
    "topicId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "citation" TEXT,
    "source" "BlockSource" NOT NULL DEFAULT 'generated',

    CONSTRAINT "Block_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Course" (
    "id" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Course_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Topic" (
    "id" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "summary" TEXT,
    "order" INTEGER NOT NULL,
    "courseId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "embedding" vector,

    CONSTRAINT "Topic_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TopicEdge" (
    "fromId" TEXT NOT NULL,
    "toId" TEXT NOT NULL,
    "kind" "EdgeKind" NOT NULL DEFAULT 'PREREQUISITE_OF',
    "confidence" DOUBLE PRECISION NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "TopicEdge_pkey" PRIMARY KEY ("fromId","toId","kind")
);

-- CreateTable
CREATE TABLE "TopicGroup" (
    "id" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "TopicGroup_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "_TopicGroups" (
    "A" TEXT NOT NULL,
    "B" TEXT NOT NULL
);

-- CreateIndex
CREATE UNIQUE INDEX "Block_topicId_order_key" ON "Block"("topicId" ASC, "order" ASC);

-- CreateIndex
CREATE UNIQUE INDEX "Course_slug_key" ON "Course"("slug" ASC);

-- CreateIndex
CREATE INDEX "Topic_embedding_idx" ON "Topic"("embedding" ASC);

-- CreateIndex
CREATE UNIQUE INDEX "Topic_slug_key" ON "Topic"("slug" ASC);

-- CreateIndex
CREATE INDEX "TopicEdge_fromId_idx" ON "TopicEdge"("fromId" ASC);

-- CreateIndex
CREATE INDEX "TopicEdge_toId_idx" ON "TopicEdge"("toId" ASC);

-- CreateIndex
CREATE UNIQUE INDEX "TopicGroup_slug_key" ON "TopicGroup"("slug" ASC);

-- CreateIndex
CREATE UNIQUE INDEX "_TopicGroups_AB_unique" ON "_TopicGroups"("A" ASC, "B" ASC);

-- CreateIndex
CREATE INDEX "_TopicGroups_B_index" ON "_TopicGroups"("B" ASC);

-- AddForeignKey
ALTER TABLE "Block" ADD CONSTRAINT "Block_topicId_fkey" FOREIGN KEY ("topicId") REFERENCES "Topic"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Topic" ADD CONSTRAINT "Topic_courseId_fkey" FOREIGN KEY ("courseId") REFERENCES "Course"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TopicEdge" ADD CONSTRAINT "TopicEdge_fromId_fkey" FOREIGN KEY ("fromId") REFERENCES "Topic"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TopicEdge" ADD CONSTRAINT "TopicEdge_toId_fkey" FOREIGN KEY ("toId") REFERENCES "Topic"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "_TopicGroups" ADD CONSTRAINT "_TopicGroups_A_fkey" FOREIGN KEY ("A") REFERENCES "Topic"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "_TopicGroups" ADD CONSTRAINT "_TopicGroups_B_fkey" FOREIGN KEY ("B") REFERENCES "TopicGroup"("id") ON DELETE CASCADE ON UPDATE CASCADE;

