# Change-Aware Rerun Rollout

This rollout is intentionally staged. The `PipelineState` migration and the
first fingerprint-writing run both mutate durable state, so do not start in
production.

## Order

1. Apply the Prisma migration only to scratch or dev.
   First run the DB write guard preflight:

   ```bash
   PIPELINE_DB_TARGET=dev python -m pipeline.db_guard
   ```

   If the target is genuinely non-production but the URL does not contain an
   obvious marker, the guard still allows it as long as the resolved Supabase
   ref is not the version-controlled production ref.

   ```bash
   export PIPELINE_DB_TARGET=dev
   python -m pipeline.db_guard
   npx prisma migrate deploy
   ```

   Production is deliberately annoying and must be explicit:

   ```bash
   PIPELINE_DB_TARGET=prod PIPELINE_ALLOW_PROD_WRITES=1 \
     python -m pipeline.db_guard

   PIPELINE_DB_TARGET=prod PIPELINE_ALLOW_PROD_WRITES=1 \
     npx prisma migrate deploy
   ```

2. Run one full course fixture and save the JSON report.
3. Rerun the same fixture with no input changes and save the JSON report.
4. Validate the no-op report:

   ```bash
   python -m pipeline.rerun_canary noop --report reports/<noop-report>.json
   ```

5. Run the intentional-change matrix:
   - source chunk content/hash change
   - prompt version change
   - Agent 3 model change with no prompt-version bump
   - decoding parameter change
   - manual anchor/content change

6. Run a full-versus-incremental canary:

   ```bash
   python -m pipeline.rerun_canary compare \
     --full-report reports/<full-report>.json \
     --incremental-report reports/<incremental-report>.json
   ```

7. Only after scratch/dev evidence is clean, prepare production rollout.

## Production Backfill Policy

Existing generated blocks from before this rollout do not have
`generation_metadata.context_fingerprint`. The safe default is to let the first
`--stale-only` production run regenerate those topics. That produces fresh
blocks whose metadata honestly records the current model, decoding parameters,
prompt version, output format version, chunks, prereqs, and pinned anchors.

Backfill is an explicit baseline-acceptance operation. Running it with `--apply`
means: "the current generated blocks are acceptable as the initial baseline for
change-aware reruns, even though they may not have been produced by the current
Agent 3 config."

Use backfill only when avoiding a production-wide regeneration pass is more
important than reissuing content under the current generator.

## Backfill Workflow

Dry-run first:

```bash
python -m pipeline.backfill_context_fingerprints --course <course-slug>
```

Review the JSON lines:

- `would_backfill`: generated blocks are missing `context_fingerprint` and can
  be marked with the current computed fingerprint.
- `already_current`: at least one stored fingerprint already matches the current
  context.
- `needs_regeneration`: stored fingerprints exist but do not match the current
  context; do not backfill these rows.
- `skipped/no_blocks`: nothing to do.

Apply only after review:

```bash
python -m pipeline.backfill_context_fingerprints --course <course-slug> --apply
```

The apply path only updates non-manually-edited blocks. It preserves existing
metadata and adds:

- `context_fingerprint`
- `context_fingerprint_backfilled_at`
- `context_fingerprint_backfill_policy`

Manual anchors are not modified. They still participate in the computed
fingerprint, so later anchor edits correctly make the topic stale.

## Never

- Do not run migration or backfill against production before scratch/dev fixture
  evidence exists.
- Do not backfill topics with mismatched existing fingerprints.
- Do not treat backfill as proof the current model would produce the same
  blocks. It is only a baseline acceptance marker.
