/*
  Warnings:

  - You are about to drop the column `language` on the `Block` table. All the data in the column will be lost.
  - Changed the type of `type` on the `Block` table. No cast exists, the column would be dropped and recreated, which cannot be done if there is data, since the column is required.
  - Changed the type of `content` on the `Block` table. No cast exists, the column would be dropped and recreated, which cannot be done if there is data, since the column is required.

*/
-- CreateEnum
CREATE TYPE "BlockType" AS ENUM ('paragraph', 'heading', 'bulletListItem', 'numberedListItem', 'codeBlock', 'math', 'plot', 'callout');

-- DropIndex
DROP INDEX "Topic_embedding_idx";

-- AlterTable
ALTER TABLE "Block" DROP COLUMN "language",
ADD COLUMN     "generation_metadata" JSONB,
ADD COLUMN     "group_id" TEXT,
DROP COLUMN "type",
ADD COLUMN     "type" "BlockType" NOT NULL,
DROP COLUMN "content",
ADD COLUMN     "content" JSONB NOT NULL;

-- CreateIndex
CREATE INDEX "Block_group_id_idx" ON "Block"("group_id");

-- CreateIndex
CREATE INDEX "Block_topicId_group_id_idx" ON "Block"("topicId", "group_id");
