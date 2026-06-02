-- Course-level pipeline stage state for change-aware reruns.
CREATE TABLE "PipelineState" (
    "id" TEXT NOT NULL,
    "courseId" TEXT NOT NULL,
    "stage" TEXT NOT NULL,
    "subjectKey" TEXT NOT NULL,
    "fingerprint" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "metadata" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PipelineState_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "PipelineState_courseId_stage_subjectKey_key"
ON "PipelineState"("courseId", "stage", "subjectKey");

CREATE INDEX "PipelineState_courseId_stage_idx"
ON "PipelineState"("courseId", "stage");

ALTER TABLE "PipelineState"
ADD CONSTRAINT "PipelineState_courseId_fkey"
FOREIGN KEY ("courseId") REFERENCES "Course"("id") ON DELETE CASCADE ON UPDATE CASCADE;
