-- Add admin-authored image blocks. Agent 3 still does not emit these.
ALTER TYPE "BlockType" ADD VALUE IF NOT EXISTS 'image';

-- Supabase Storage bucket for uploaded block images. Keep this conditional so
-- non-Supabase local databases can still apply the schema migration.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage'
  ) THEN
    EXECUTE $sql$
      INSERT INTO storage.buckets (id, name, public)
      VALUES ('block-images', 'block-images', true)
      ON CONFLICT (id) DO NOTHING
    $sql$;
  END IF;
END $$;
