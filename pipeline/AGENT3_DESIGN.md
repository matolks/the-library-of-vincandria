# Agent 3 Design — Teaching Block Generation

## 0. Implementation status

- §1 schema additions: **applied** to Supabase via `restructure_block_for_typing_and_grouping` migration. Citation-column removal (see §5) is a pending follow-up migration.
- §8 step 2: **partial** — chunk infrastructure (`upsert_chunks`, `delete_orphan_chunks`, `top_chunks_for_topic`) and the `Chunk` table are in place. `replace_topic_blocks` for block reconciliation is not yet written.
- §8 step 3: **partial** — `pipeline/block_gen.py` exists with `get_topic_context` and the coverage-flag / sparse-refusal logic (§6 source context). Prompt, validation, and reconciler are not yet written.
- Survey on `multivariable-calculus` (recorded in repo): two SPARSE topics (mvc-lagrange-multipliers, mvc-double-integrals), seven thin. Drives the order-of-work change in §8 (Agent 4 runs before any course-wide block_gen).

## 0.1 Locked contracts

Three rules constrain everything below. They are stated up-front because §4, §5, and §6 all depend on them.

1. **Anchor pinning is by relative order, not absolute ordinal.** An anchor block must appear in the regenerated sequence in the same relative position with respect to other anchors, with `id` and `content` byte-identical to the previous run. Its absolute slot in the new sequence is the model's call. Rationale: an anchor's original ordinal was meaningful only relative to neighbors that no longer exist after regeneration. Pinning to absolute slots preserves a coordinate, not a meaning.
2. **Group pinning is atomic.** If any block in a `group_id` cohort has `manually_edited=true`, the entire cohort is pinned as a unit. No partial-group preservation. Rationale: `group_id` exists to express coupling; preserving half a coupled unit produces broken output (a caption referencing a regenerated plot, etc.).
3. **The model never authors citation text.** Generation emits `source_chunk_ids` only. Human-readable citation text is rendered downstream from chunk metadata at display time. Rationale: removes hallucinated attributions structurally rather than by eval, and lets citation formatting evolve (style changes, metadata enrichment) without regenerating blocks.

## 1. Schema migration

Additions to `Block`:

- `type` — enum `BlockType`. Values: `paragraph`, `heading`, `bulletListItem`, `numberedListItem`, `codeBlock`, `math`, `plot`, `callout`. Deferred for v1: `image`, `table`, `diagram`, `checkListItem`.
- `content` — `jsonb`. BlockNote-shaped `{ props, content, children }`. The inline `content` array supports inline custom types (inline math, inline code, refs) so short equations live inside paragraphs without becoming separate blocks.
- `generation_metadata` — `jsonb`, nullable. Shape: `{ agent, model, prompt_version, source_chunk_ids: string[], generated_at }`. Always populated for generated blocks. Used for audit, debugging, and selective re-runs.
- `group_id` — `text`, nullable. Indexed. Blocks sharing a `group_id` form an atomic unit (see §4).

Kept unchanged: existing `id` (cuid, auto-generated) serves as the stable block identifier and aligns with BlockNote's string-ID model. `order`, `@@unique([topicId, order])`, `source`, `manually_edited` also unchanged.

**Pending removal:** `citation` column. Per contract 3, citation text is no longer stored on the block. The column will be dropped in a follow-up migration; until then, ignore it on read and never write to it from `block_gen`.

`order` sequences blocks. `id` identifies them. `group_id` couples them. This is the unlock for per-block idempotency and for keeping related blocks together across regenerations.

Also added: indexes on `group_id` and `(topicId, group_id)`. The `language` column was dropped earlier; language for code blocks lives in `content.props.language`.

## 2. BlockNote type alignment

Generated types map 1:1 onto BlockNote primitives so the admin editor renders and edits without translation.

| `BlockType`        | BlockNote primitive | Props                                                | Source                |
| ------------------ | ------------------- | ---------------------------------------------------- | --------------------- |
| `paragraph`        | `paragraph`         | none                                                 | core                  |
| `heading`          | `heading`           | `{ level: 1 \| 2 \| 3 }`                             | core                  |
| `bulletListItem`   | `bulletListItem`    | none                                                 | core                  |
| `numberedListItem` | `numberedListItem`  | none                                                 | core                  |
| `codeBlock`        | `codeBlock`         | `{ language: string }`                               | core                  |
| `callout`          | `callout`           | `{ variant: "note" \| "insight" \| "warning" }`      | core                  |
| `math`             | `math` (custom)     | `{ mode: "display", latex: string, label?: string }` | custom, KaTeX render  |
| `plot`             | `plot` (custom)     | see §3                                               | custom, Plotly render |

Inline content (lives inside the `content` array of any block above):

- inline math: `{ type: "math", latex: string }`. Renders via KaTeX inline.
- inline code, links, bold, italic: BlockNote core inline content.

Custom blocks (`math`, `plot`) and the inline math node require registration in the BlockNote editor when the admin UI is built. Block generation does not depend on the editor existing; the type definitions are the contract.

## 3. Plot block specification

`plot` blocks are spec-based, not image-based. The model emits a structured spec; the renderer draws client-side. This keeps plots editable, queryable, and regenerable.

```json
{
  "kind": "function2d" | "surface3d" | "levelcurves" | "vectorfield" | "parametric2d" | "parametric3d",
  "expression": "string or string[]",
  "domain": { "x": [number, number], "y": [number, number], "t": [number, number] },
  "labels": { "x": "string", "y": "string", "z": "string", "title": "string" }
}
```

Domain keys are kind-dependent: `function2d` needs `x`, `surface3d` and `levelcurves` need `x` and `y`, `parametric*` needs `t`. Expressions use standard math syntax (`x^2 + y^2`, `sin(x*y)`). Rendering target is Plotly via `react-plotly.js`.

The model emits plots only when a visualization materially aids the explanation. Default is no plot. Never emit base64 images, never reference external image URLs.

## 4. Block coupling

Two coupling levels, mapping to two real authoring patterns.

**Inline coupling** for short, prose-embedded math, code, or references. Handled entirely by BlockNote inline content inside a block's `content.content` array. No schema change. Most "paragraph plus equation" cases dissolve at this level because the prose and the inline math are the same row.

**Group coupling** for block-level units that must stay adjacent (typical: a display equation plus its immediately-following explanatory paragraph, or a plot plus its caption-paragraph). Implemented via `Block.group_id` under the atomic rule from contract 2:

- Same `group_id` = atomic group. Blocks within a group are ordered by `order` and are never separated during reordering, regeneration, or anchor pinning.
- **Pinned-set expansion at regen time.** `manually_edited` is ground truth for what the human actually edited — the flag stays on exactly the rows the editor saved. At regeneration, the reconciler computes the pinned set by starting from blocks with `manually_edited=true` and expanding to include every sibling sharing a `group_id` with any such block. The flag is not propagated to siblings on save; expansion is computed, not stored. Keeps the flag's meaning honest and avoids fan-out writes on every edit.
- **Anchor pinning for groups.** Per contract 1, the pinned cohort is preserved by relative order, not absolute ordinal. The cohort's internal order (the `order` values among its members from the previous run) is preserved. Its position in the regenerated sequence is the model's call, constrained only by relative order against other anchors and anchor cohorts.
- Regeneration deletes a block only if it is not in the expanded pinned set. Group integrity wins over individual block status.

Default is `group_id=NULL`. The model uses groups sparingly, only when blocks genuinely cannot stand alone.

## 5. Citation and provenance

Per contract 3, the model never authors citation text. One field, structured, written by the system:

- `Block.generation_metadata.source_chunk_ids` — string array inside the jsonb, references `Chunk.id` (cuid) rows in the `Chunk` table. Structured provenance, always populated for generated blocks (may be an empty array if no chunks materially contributed). Used by audit tooling, the future provenance UI, and the citation renderer.

**Citation rendering.** Human-readable citation text is rendered at display time by the frontend (or a shared renderer module) by joining `source_chunk_ids` against `Chunk` rows and formatting the result. Short-term renderer formats mechanically from what's currently on the chunk row:

- `sourceType` in (`pdf`, `docx`, `pptx`, `xlsx`, `ipynb`, `code`, `markdown`, `txt`): `{basename(sourcePath)} p.{pageNumber}` when `pageNumber` is present, `{basename(sourcePath)}` otherwise.
- `sourceType='web'` (introduced by Agent 4, see §7): `{title or domain} ({domain}, accessed YYYY-MM-DD)`, with the URL preserved in `sourcePath`.

Long-term, parsers will populate structured bibliographic metadata on `Chunk` (title, authors, edition, identifier, locator) and the renderer upgrades transparently — no block regeneration required.

**Removed:** `Block.citation` column. To be dropped in a follow-up migration. `block_gen` never writes it.

**Stability note.** Chunk IDs are stable across extractor re-runs because chunks upsert on `(courseId, sourcePath, chunkIndex)`. References survive most edits but may dangle if a source file is deleted or chunks are reordered. Acceptable for v1; if it becomes a problem, add `source_chunk_hashes: string[]` alongside.

## 6. Generation contract

**Input per topic.** Three components:

1. **Topic context.** The topic's `slug`, `title`, `summary`, and `course` slug.
2. **Prereq context.** 1-hop prereq topics via `TopicEdge` (topics where `toId = target.id, kind = PREREQUISITE_OF`). For each, pass `slug`, `title`, `summary`. Gives the model knowledge of what's already been taught so it doesn't re-explain basics.
3. **Source context.** Top-K chunks via `db.top_chunks_for_topic(topic_id, k=8)`, course-scoped pgvector ANN against the topic's embedding. Each chunk passes its `content`, `sourcePath`, `pageNumber`, `id`, and computed `similarity` (1 - cosine distance). Chunks below the `chunk_similarity_floor` (default 0.70) are excluded from the prompt.

Plus the expanded pinned set (see §4) passed as anchors.

**Coverage flag and sparse refusal.** `get_topic_context` computes a `coverage` flag from the _unfiltered_ top-K. If no chunk clears `chunk_similarity_floor`, coverage is `'sparse'` and the returned `TopicContext.chunks` is empty. `block_gen` MUST refuse to generate on sparse topics and emit a structured refusal so the orchestrator can record the topic as needing Agent 4 enrichment. Rationale: generating on sparse coverage produces teaching prose grounded in chunks that aren't actually about the topic; the model fills the gap from its own knowledge and the citation renderer dutifully attaches attributions that don't support the claims. Refusing structurally is the only correct behavior. The same flag is the input queue for Agent 4.

**Prompt output.** Strict JSON: an ordered array of blocks conforming to the type table and the inline content shape. Anchor blocks appear in the array with their `id` and `content` byte-identical to the input. The model decides absolute placement; it must preserve relative order among anchors and keep grouped anchors contiguous. Generated blocks have no `id` in the model output; the writer assigns one at insert.

**Validation.** Two layers, both with one retry on failure.

1. **Schema validation.** Parse, validate every block against the type enum, props shape, and (where applicable) the plot spec or math shape. No silent coercion.
2. **Anchor integrity validation.** Every anchor block from the input must appear in the output. For each: `id` matches, `content` is byte-identical (canonicalized JSON compare), grouped anchors remain contiguous and in their original internal order. Any violation fails the run and retries once with the violation appended to the prompt as a correction turn. Retries use the same temperature setting; the violation message itself is what changes the output.

**Chunk policy.** Chunks are background context, not authoritative source. The model writes teaching prose; it does not stitch chunks together. When a generated block materially draws on chunk content, the model populates `generation_metadata.source_chunk_ids` with those chunk IDs. The model does not emit citation text (contract 3); that is rendered downstream from the chunk IDs.

**Idempotency.** Per-block, anchors pinned. On re-run for a topic:

1. Fetch existing blocks. Compute the pinned set per §4: blocks with `manually_edited=true` plus all siblings sharing their `group_id`.
2. Pass the pinned set to the prompt with each block's `content`, `id`, previous `order`, and `group_id`. Instruct the model that these are immutable, must appear in the output with `id` and `content` unchanged, must preserve their relative order, and must keep grouped cohorts contiguous in their original internal order. Absolute placement is the model's choice.
3. Model returns the full ordered sequence with anchors integrated and new blocks interleaved.
4. Transaction: delete every block on this topic not in the pinned set, insert new generated blocks with fresh `id`s, leave pinned rows untouched, rewrite `order` densely across the merged sequence following the model's emitted ordering. Single transaction so `@@unique([topicId, order])` holds throughout.

**Cost reporting.** Return `{ topics_processed, blocks_written, input_tokens, output_tokens, usd_cost }` matching the mapper shape, for `ingest.py` to aggregate. Per-topic token totals also logged (block_gen variance is wider than mapper's — flagged in the parent status doc).

**CLI.** `python -m pipeline.block_gen --course <slug> [--topic <slug>] [--dry-run]`. Course scope mirrors mapper. Single-topic flag for iteration.

## 7. Agent 4 — Web enrichment (the boundary block_gen depends on)

Agent 4 was originally deferred. The mvc survey moved it forward: only five of eighteen mvc topics have ≥3 chunks above 0.75 similarity, the corpus is exam-prep / HW-solutions rather than textbook, and two topics (Lagrange multipliers, double integrals) have zero relevant coverage. Web enrichment is no longer "patch sparse outliers"; it is structurally required to give block_gen the conceptual scaffolding the source corpora typically lack. This section locks the architecture so Agent 3 and Agent 4 develop against the same contract.

**Pipeline position.** Agent 4 runs between Mapper (Agent 2) and block_gen (Agent 3). Order: extract → map → enrich → generate. Each agent leaves the database in a state the next reads. No inline coupling.

**Storage: web content becomes `Chunk` rows.** Web fetches are upserted into the same `Chunk` table as local source. Same schema, same retrieval path (`top_chunks_for_topic`), same provenance pattern. block_gen does not know or care that some chunks came from the web. Discriminator is `Chunk.sourceType`:

- `sourceType='web'`
- `sourcePath` holds the canonical URL (not a filename).
- `pageNumber` is null; `sectionPath` may carry the page section header (`H2` heading or fragment).
- `contentHash` for dedup the same way local chunks have it; re-fetching an unchanged page is a no-op.
- A `web_metadata` jsonb column may be added later for `title`, `domain`, `accessedAt`, `author`. v1 derives these at render time; the column is schema-additive when needed.

**Trigger.** Automatic on `coverage='sparse'` from `TopicContext`. Also runs for `'thin'` topics (defined as: fewer than N chunks above strong floor; default N=3, strong floor 0.75) when invoked with `--include-thin`. Manual per-topic override via CLI flag. Sparse and thin queues are derivable from `chunk_survey survey` output.

**Source policy.** Three tiers, hard-enforced at the fetcher.

- **Tier 1, preferred:** Wikipedia, MIT OpenCourseWare, Wolfram MathWorld. Known licensing (CC-BY-SA, CC-BY-NC, MathWorld terms), structured content, citation-friendly. Substantive quotation allowed within fair-use limits stated in the parent project's copyright rules.
- **Tier 2, cite-and-link, paraphrase-only:** Paul's Online Math Notes, university lecture notes hosted on `.edu` domains (PDFs, HTML), Khan Academy public pages. Agent 4 stores chunks; block_gen treats them as paraphrase sources only. The prompt instructs the model never to quote Tier 2 sources verbatim.
- **Forbidden:** copyrighted textbooks, Chegg/CourseHero/StudyBlue, any auth-walled or paywalled content, any aggregator that itself violates source copyrights. Hard refusal at the fetcher, enforced by allow-list rather than block-list.

**Fetch budget.** Per-topic cap on fetches (default 5 pages, configurable); per-course cap on total fetches (default 100); per-domain rate limit. Cache by URL+contentHash; re-runs hit the cache. Same idempotency contract as Agent 1.

**Citation interaction.** The renderer described in §5 learns one new branch: `sourceType='web'` rows render as `{title} ({domain}, accessed YYYY-MM-DD)` with the URL preserved. Block_gen and the generation contract are unchanged — citation rendering is a frontend concern (contract 3).

**Deferred for Agent 4 v1:**

- Search-then-fetch (use web_search to discover candidate URLs vs. directly fetching from a curated URL list).
- LLM-summarized chunks vs. raw HTML-to-text chunks. v1: raw text via the standard chunker. Summarization can come later.
- Recurrent re-enrichment when the source changes upstream. v1: fetch once, refresh manually.
- Multi-language sources. v1: English only.
- Domain-specific extractors (PDF lecture-notes, Wikipedia infoboxes). v1: generic HTML / PDF chunking via existing parsers.

A separate `pipeline/AGENT4_DESIGN.md` will detail the prompt, fetcher implementation, and source-policy enforcement when work on Agent 4 starts. This section is the contract Agent 3 depends on.

## 8. Deferred past v1

- `image` blocks. Need an asset pipeline. Defer until web enrichment or admin upload exists.
- `table` blocks. Defer until a course needs structured tabular content.
- `diagram` blocks (mermaid/DOT). Prereq DAG already lives in `GraphViewer.tsx`, separate from the block stream. Defer block-level diagrams until a course needs them.
- Block-level prereqs (`Block.prereqTopicIds`). Schema-additive when needed.
- Multiple explanations per block (A/B variants). Schema-additive when needed.
- Anchor staleness detection. An anchor may reference content that no longer exists after regeneration (e.g., refers to "the equation above" but the surrounding context changed). Flag in the eval harness later; do not solve in v1.
- Hash-based chunk provenance (`source_chunk_hashes`) for cross-run reference stability. Add if ID-based references start dangling at scale.
- Structured bibliographic metadata on `Chunk` (title, authors, edition, identifier, locator) for richer citation rendering. Renderer contract is stable across this upgrade.
- Retry-with-temperature-bump on validation failure. Current spec retries with the same temperature plus a correction message; if that proves insufficient empirically, escalate.
- `'thin'` as a distinct coverage state separate from `'dense'` and `'sparse'`. v1 treats anything above floor as dense for the refusal decision; thin coverage triggers Agent 4 only when `--include-thin` is passed. Promote thin to a first-class TopicContext value when block_gen evals show thin coverage degrades output quality measurably.

**Promoted to v1** (previously deferred): chunk similarity floor on `top_chunks_for_topic`. Implemented as `chunk_similarity_floor` (default 0.70) in `get_topic_context`, with the `coverage` flag and sparse-refusal protocol in §6.

## 9. Order of work

1. ✅ Prisma migration: `type`, `content` jsonb, `generation_metadata`, `group_id`. Indexes on `group_id` and `(topicId, group_id)`. Pushed to Supabase.
2. ⏳ Update `pipeline/db.py`:
   - ✅ Chunk infrastructure: `ChunkRecord`, `upsert_chunks`, `delete_orphan_chunks`, `top_chunks_for_topic`. Chunk table populated for mvc (94 rows with embeddings).
   - ❌ `replace_topic_blocks(topic_id, pinned, generated)` for the group-aware transactional swap per §6 step 4. Built next, tested against fixtures before any LLM is wired in.
3. ⏳ `pipeline/block_gen.py`:
   - ✅ `get_topic_context` with `coverage` flag and sparse refusal (§6). Lives in `block_gen.py` for now; the read primitives (`_fetch_topic`, `_fetch_prereqs`, `_fetch_blocks`) can migrate to `db.py` if Agent 4 ends up needing them.
   - ❌ Reconciler implementation calling `replace_topic_blocks`. Fixture tests first.
   - ❌ Prompt construction. Output JSON schema includes `group_id` and the math/plot block shapes. JSON schemas for custom block types emitted into the prompt so output validates.
   - ❌ Schema validation and anchor integrity validation per §6, both with one retry.
4. ❌ Reconciler fixture tests before any real generation run. Cases: no anchors, one ungrouped anchor, one grouped anchor (full cohort pinned), all-pinned group, generated array shorter than anchor count, generated array longer than expected, anchor with `id` mismatch, anchor with mutated content, grouped anchors with broken contiguity in model output.
5. ❌ Validate block_gen happy path on the strongest-coverage mvc topic (`mvc-quadric-surfaces`, top similarity 0.878, 8 strong chunks). Inspect blocks by eye. Math-heavy and plot-bearing topics come after.
6. ❌ Agent 4 design and build per §7 architecture: `pipeline/enricher.py`, source-policy allow-list, fetch cache, chunk upsert with `sourceType='web'`. Separate design doc.
7. ❌ Run Agent 4 against mvc sparse topics (mvc-lagrange-multipliers, mvc-double-integrals), then thin topics with `--include-thin`. Re-run `chunk_survey survey` to confirm coverage states changed.
8. ❌ Run block_gen across full mvc course. Test manually_edited cases: ungrouped singleton, block inside a group, entire group pinned, manually-deleted pinned block between runs, pinned block whose `group_id` no longer matches anything in the regenerated set.

## 10. Custom BlockNote blocks (frontend, for later reference)

Registration is a few dozen lines per type. The block_gen pipeline does not depend on the editor; these are the editor-side counterparts of the schema decisions above.

- `math` block — KaTeX render, props `{ mode: "display", latex, label? }`.
- inline `math` — KaTeX inline render, props `{ latex }`.
- `plot` block — Plotly render via `react-plotly.js`, props per §3.
- `callout` block — BlockNote core, configure variants `note | insight | warning`.

The citation renderer module (per §5) also lives frontend-side. It accepts `source_chunk_ids`, fetches/joins chunk metadata, and formats according to the active citation style. v1 implementation is mechanical and handles two `sourceType` branches: local files (basename + optional page) and web (title + domain + accessedAt, per §7). Future versions read enriched chunk metadata once parsers populate it.
