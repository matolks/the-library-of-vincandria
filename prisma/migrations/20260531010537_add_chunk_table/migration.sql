-- CreateTable
CREATE TABLE "Chunk" (
    "id" TEXT NOT NULL,
    "courseId" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "contentHash" TEXT NOT NULL,
    "sourcePath" TEXT NOT NULL,
    "sourceType" TEXT NOT NULL,
    "chunkIndex" INTEGER NOT NULL,
    "pageNumber" INTEGER,
    "sectionPath" TEXT,
    "tokenCount" INTEGER,
    "embedding" vector(1024),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Chunk_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "Chunk_courseId_idx" ON "Chunk"("courseId");

-- CreateIndex
CREATE INDEX "Chunk_contentHash_idx" ON "Chunk"("contentHash");

-- CreateIndex
CREATE UNIQUE INDEX "Chunk_courseId_sourcePath_chunkIndex_key" ON "Chunk"("courseId", "sourcePath", "chunkIndex");

-- AddForeignKey
ALTER TABLE "Chunk" ADD CONSTRAINT "Chunk_courseId_fkey" FOREIGN KEY ("courseId") REFERENCES "Course"("id") ON DELETE CASCADE ON UPDATE CASCADE;
