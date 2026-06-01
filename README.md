# The Library of Vincandria

A personal knowledge graph that transforms raw university course materials into a structured, publicly browsable website. A local Ollama model parses and chunks your files. Claude API agents extract concepts, map relationships, and generate teaching content. You refine everything through an admin block editor.

This is the first module running on AIStack, a local AI platform designed to support multiple independent projects. Future modules plug into the same platform without touching this codebase.

**Live site:** `[url when deployed]`
**Local platform:** AIStack, `/Volumes/AIStack/modules/knowledge/`

---

## Status

| Stage                              | Status      |
| ---------------------------------- | ----------- |
| Schema (Prisma + Supabase)         | Done        |
| Chunker (Ollama, Stage 1)          | Done        |
| Agent 1 — Extractor (topics)       | Done        |
| Agent 2 — Mapper (dependencies)    | Done        |
| Agent 3 — Block Generator          | Done, v4 QA |
| Agent 4 — Web Enricher             | Done, v1    |
| Course pipeline orchestrator       | Done, CLI   |
| Eval harness (`pipeline/evals/`)   | Done, v1    |
| Public website                     | Done, v1    |
| Admin dashboard + BlockNote editor | Not started |

---

## How it works

```
AIStack (your drive)           This repo                        Public
/modules/knowledge/docs/  →   pipeline/ parses + processes  →  website renders
      course files              writes to Supabase               from database
```

You drop files onto the drive and run the course pipeline. The pipeline has one local stage and four API-backed agents:

**Stage 1, Local (Ollama).** Reads every file, extracts raw text, and chunks it into clean passages. Tags chunks with `source_type` (lectures, exams, homework, reference, topics) inferred from the folder structure. No API calls. Nothing leaves your machine.

**Stage 2, Claude API + Voyage.** Agents run in sequence on the chunked text: extract topics and assign them to broad groups, map dependencies between topics, enrich sparse/thin topics with allow-listed web chunks, then generate teaching blocks for each topic. Results write to Supabase. Both topics and the prerequisite graph live in Postgres (the graph as a `TopicEdge` table queried via recursive CTEs). The website reflects changes immediately.

When you add new material, drop the files in and run the command again. The pipeline is idempotent. It upserts existing records rather than duplicating them. Blocks you have manually edited in the admin are flagged and skipped on re-ingestion.

---

## Model split

| Task                                    | Model                          | Why                                                                               |
| --------------------------------------- | ------------------------------ | --------------------------------------------------------------------------------- |
| File parsing, text extraction, chunking | Ollama (local)                 | Deterministic, high-volume, no reasoning needed. Data stays local.                |
| Topic embeddings (1024-dim)             | Voyage `voyage-3.5-lite` (API) | Strong retrieval quality at low cost. Used by the mapper for candidate retrieval. |
| Topic extraction + group assignment     | Claude API                     | Requires consistent structured JSON output across varied content.                 |
| Dependency mapping                      | Claude API                     | Requires cross-topic directional reasoning.                                       |
| Block generation (teaching content)     | Claude API                     | Teaching quality depends on reasoning depth and schema-following.                 |
| Web enrichment                          | Curated HTTPS fetch + Voyage   | Adds allow-listed web chunks into the same retrieval/provenance path.             |

---

## Local structure (AIStack)

```
/Volumes/AIStack/
├── core/
│   ├── memory/
│   │   ├── history.json
│   │   ├── memory.json
│   │   └── episodic.json
│   └── logs/
│       └── chat_log.jsonl
│
├── modules/
│   ├── knowledge/
│   │   └── docs/
│   │       ├── operating-systems/
│   │       │   ├── lectures/
│   │       │   ├── exams/
│   │       │   └── homework/
│   │       ├── multivariable-calculus/
│   │       └── .../
│   ├── email/
│   └── .../
│
├── rag/
│   └── chroma/                # (optional, unused by current pipeline)
│
├── ollama-models/
└── README.md
```

Course folders may contain subfolders (`lectures/`, `exams/`, `homework/`, `reference/`, `topics/`). The chunker uses the folder name to tag each chunk's source type. The AI determines which broad topic groups each course belongs to from content. A course like Signals and Systems spans both Math Foundations and Signals and Networks, and the agent figures that out without you deciding upfront.

The graph database directory (`graphs/course_graph/`) is no longer used. Kuzu was evaluated and rejected in favor of Postgres `TopicEdge` with recursive CTEs, which handles transitive prereqs and topological sort at expected scale without a second store.

---

## Repo structure

```
the-library-of-vincandria/
├── app/
│   ├── admin/
│   │   ├── page.tsx               # admin dashboard
│   │   ├── editor/                # BlockNote editor per topic
│   │   └── upload/                # Phase 2: trigger pipeline from browser
│   ├── api/
│   │   ├── topics/
│   │   ├── blocks/
│   │   └── pipeline/              # Phase 2: triggers Python pipeline
│   ├── [group]/
│   │   └── [course]/
│   │       └── [topic]/           # topic page, renders blocks in order
│   ├── components/
│   │   ├── TopNav.tsx
│   │   ├── BlockRenderer.tsx
│   │   └── GraphViewer.tsx
│   ├── lib/
│   │   ├── prisma.ts
│   │   └── auth.ts
│   ├── globals.css
│   ├── layout.tsx
│   └── page.tsx
│
├── prisma/
│   └── schema.prisma
│
├── pipeline/
│   ├── course_orchestrator.py     # extractor -> mapper -> enricher -> block_gen, with aggregate status/cost
│   ├── chunker.py                 # Ollama: parse files, extract text, chunk
│   ├── embeddings.py              # Voyage embeddings (1024-dim, batched)
│   ├── extractor.py               # Claude Agent 1: topics + group assignment
│   ├── mapper.py                  # Claude Agent 2: prereq graph → Postgres TopicEdge
│   ├── block_gen.py               # Claude Agent 3 CLI + topic context/target resolution
│   ├── orchestrator.py            # Agent 3 per-topic generation/retry/reconcile flow
│   ├── prompt.py                  # Agent 3 prompt contract
│   ├── block_schema.py            # generated block schema validation
│   ├── anchor_integrity.py        # pinned/manual block integrity validation
│   ├── llm.py                     # Anthropic wrapper + token/cost accounting
│   ├── enricher.py                # Agent 4 web chunks for sparse/thin topics
│   ├── parsers/
│   │   ├── pdf.py                 # pymupdf
│   │   ├── docx.py                # python-docx
│   │   ├── xlsx.py                # openpyxl
│   │   ├── pptx.py                # python-pptx
│   │   ├── ipynb.py               # nbformat
│   │   └── code.py                # raw text + language tag
│   ├── db.py                      # Supabase write client + pgvector retrieval + block reconciliation
│   └── evals/                     # live DB eval/regression harness
│
├── scripts/
│   ├── query_prereqs.py           # query 1-hop and transitive prereqs for a topic
│   └── drop_bad_edges.py          # manual mapper fixes; promoted to eval seed data
│
├── types/
├── AGENTS.md
├── CLAUDE.md
├── .env                           # never commit
└── README.md
```

---

## The pipeline

### Stage 1, Chunker (Ollama, local)

`pipeline/chunker.py`

Reads each file through the appropriate parser, extracts raw text, and splits it into clean passages. Tags each chunk with the source type inferred from its parent folder. No API calls made here.

```json
{
  "course": "multivariable-calculus",
  "file": "lecture3.pdf",
  "source_type": "lectures",
  "page": 4,
  "chunk_index": 2,
  "text": "The dot product of two vectors..."
}
```

### Stage 2, Claude API agents

**Agent 1, Extractor** (`pipeline/extractor.py`)

Takes chunked text per course. Returns topics with summaries, key concepts, and broad group assignments. One topic can belong to multiple groups. Groups are assigned by the model based on content. Your predefined list is passed as a suggestion, not a constraint. Course slugs are never used as group slugs. Existing topic slugs are passed back to the model as anchors to prevent slug drift across re-runs. After upsert, orphan topics (no chunks left supporting them) are cleaned up. Embeddings are batched and written via Voyage.

```json
{
  "course": "Multivariable Calculus",
  "new_groups": [],
  "topics": [
    {
      "title": "Cross Product",
      "slug": "mvc-cross-product",
      "summary": "Operation on two 3D vectors producing a perpendicular vector.",
      "key_concepts": ["right-hand rule", "determinant form", "geometric area"],
      "groups": ["math-foundations"],
      "order_in_course": 4
    }
  ]
}
```

**Agent 2, Mapper** (`pipeline/mapper.py`)

Builds the prerequisite graph for a course. For each topic, retrieves the top-K (default 30) most similar topics via pgvector cosine ANN on `Topic.embedding`. The LLM then judges which candidates are genuine prerequisites of the target. Output edges are validated (slug exists, no self-edges, no duplicates, confidence ≥ 0.6), deduped, and cycle-checked via DFS. Writes are idempotent: all edges touching the course's topics are deleted before insertion. Prints token usage and per-run cost. Supports `--dry-run`.

Cross-course retrieval is supported by the schema but gated behind a planned `--cross-course` flag; for now, candidates are course-scoped.

```json
{
  "prerequisites": [
    { "from_slug": "mvc-vectors-3d", "confidence": 0.97, "reason": "..." },
    { "from_slug": "mvc-dot-product", "confidence": 0.9, "reason": "..." }
  ]
}
```

Two helper scripts ship alongside:

- `scripts/query_prereqs.py <topic-slug>` prints 1-hop prereqs and all transitive ancestors with depth (via recursive CTE). Used for sanity-checking the graph.
- `scripts/drop_bad_edges.py` deletes known-wrong edges identified in manual review. These four edges are the seed data for the eval harness.

**Agent 3, Block Generator** (`pipeline/block_gen.py`, `pipeline/orchestrator.py`)

Takes one topic at a time. It retrieves prerequisite topics, top source chunks, and existing blocks, then asks Claude to return a complete ordered teaching page as strict JSON. Output is validated before any write: block schema, anchor integrity, and source chunk IDs all have to pass.

Agent 3 refuses sparse topics before prompt construction. Sparse/thin coverage is fixed by Agent 4, then generation is retried. For manually edited blocks, the generator uses relative-order anchor pinning:

- A manually edited ungrouped block is pinned as a singleton.
- If any block in a `group_id` is manually edited, the whole group is pinned atomically.
- The model must copy pinned anchor `id`, `content`, and `group_id` exactly, preserve relative anchor order, and keep grouped anchors contiguous.
- Non-pinned blocks are replaced transactionally via `db.replace_topic_blocks`.

Generated blocks use BlockNote-shaped JSON and record structured provenance in `generation_metadata.source_chunk_ids`. The model never writes citation prose; citation rendering is downstream.

```json
{
  "blocks": [
    {
      "type": "heading",
      "content": [{ "type": "text", "text": "Lagrange Multipliers" }],
      "props": { "level": 1 },
      "generation_metadata": { "source_chunk_ids": [] }
    },
    {
      "type": "math",
      "content": [],
      "props": {
        "mode": "display",
        "latex": "\\nabla f(x,y) = -\\lambda\\,\\nabla g(x,y)"
      },
      "generation_metadata": {
        "source_chunk_ids": ["e158233e-ce9a-471d-97a9-0ffcc8a1404f"]
      }
    }
  ]
}
```

Agent 3 CLI:

```bash
# Inspect one topic's retrieval context and pinning state
python3 -m pipeline.block_gen --topic-slug mvc-lagrange-multipliers

# Generate a course without writing
python3 -m pipeline.block_gen --course multivariable-calculus --dry-run --json

# Persist, with optional pacing to avoid Anthropic output-token rate limits
python3 -m pipeline.block_gen --course multivariable-calculus --json --pause-seconds 75
```

**Agent 4, Enricher** (`pipeline/enricher.py`)

Adds allow-listed web pages as `Chunk` rows with `sourceType='web'`, then embeds them with Voyage so Agent 3 sees them through the same `top_chunks_for_topic` retrieval path as local source chunks. V1 uses curated URLs for known sparse topics and can include thin topics.

Source policy is intentionally narrow: exact allow-list hosts such as Wikipedia, MIT OCW, MathWorld, OpenStax, Paul's Online Math Notes, and Khan Academy, plus `.edu` hosts. Raw web text is chunked, cached under `.cache/agent4`, embedded, and upserted by `(courseId, sourcePath, chunkIndex)`.

```bash
# Dry-run sparse-topic enrichment
python3 -m pipeline.enricher --course multivariable-calculus --dry-run

# Include thin topics as well as sparse topics
python3 -m pipeline.enricher --course multivariable-calculus --include-thin
```

**Course orchestrator** (`pipeline/course_orchestrator.py`)

Runs `extractor -> mapper -> enricher -> block_gen` and emits one aggregate JSON report with stage statuses, input/output tokens, cache tokens, and USD cost.

```bash
python3 -m pipeline.course_orchestrator --course multivariable-calculus --dry-run --include-thin
python3 -m pipeline.course_orchestrator --course multivariable-calculus --include-thin
```

**Content judge** (`pipeline/judge.py`)

Runs after block generation and emits a mechanical QA report under `reports/`. The judge is a pre-filter, not the final editor: use it to find category clusters that should be fixed in prompts, and to identify isolated high-severity factual errors for manual review.

```bash
# Judge a full course
python3 -m pipeline.judge --course multivariable-calculus --pause-seconds 1

# Judge one topic
python3 -m pipeline.judge --course multivariable-calculus --topic mvc-quadric-surfaces
```

Triage rule:

- High findings: fix before feature work. Factual errors are non-negotiable. Missing plots on geometry topics usually mean the prompt still is not explicit enough.
- Medium findings: cluster by category. If one category dominates across topics, fix the prompt or renderer contract; if it appears once, defer to manual editing.
- Low findings: bookmark for the admin editor. Do not rerun the whole pipeline for polish.

---

## Topic groups

Suggested to the model. It assigns based on content and can create new groups if a course doesn't fit cleanly.

| Group                     | Examples                                   |
| ------------------------- | ------------------------------------------ |
| Math Foundations          | Calculus, Linear Algebra, Fourier Analysis |
| Engineering Foundations   | VLSI, FPGA Design                          |
| Programming & Software    | Data Structures, Algorithms, OS internals  |
| Computer Systems          | Operating Systems, Computer Architecture   |
| Hardware & Circuits       | Digital Logic, Electronics                 |
| Signals & Networks        | DSP, Networking, Communications            |
| Engineering Communication | Technical Writing, Documentation           |

---

## Database schema

Four levels: `TopicGroup ⇄ Topic → Block`, with `Course` grouping topics within a single class, and `TopicEdge` carrying the prerequisite graph.

`Topic` to `TopicGroup` is many-to-many (a topic like "Convolution" belongs to both Math Foundations and Signals & Networks). `Topic` to `Course` is many-to-one. `TopicEdge` is a self-referential relation on `Topic` with a `kind` enum (currently only `PREREQUISITE_OF`) and a `confidence` float.

The `manually_edited` flag on `Block` is critical. When block generation reruns, any manually edited block becomes an anchor. If it belongs to a `group_id`, the full group is pinned atomically so generated content cannot split a coupled equation/caption or plot/explanation pair. This is what lets you edit content in the admin without the pipeline overwriting your work. Any block edited through the admin API should set this flag automatically once the editor exists.

`Block.source` records broad provenance (`local`, `web`, `manual`, `generated`). Generated block provenance lives in `Block.generation_metadata`, especially `source_chunk_ids`, which references `Chunk.id`. Human-readable citations are rendered downstream from chunk metadata. `Block.citation` still exists in the schema for older code but Agent 3 does not write citation text.

`Topic.embedding` is a 1024-dim `vector` column with an HNSW index, populated by Voyage during extraction and queried by the mapper via cosine distance (`<=>`).

`Chunk.embedding` is also a 1024-dim `vector`, populated for both local and Agent 4 web chunks. Agent 3 retrieves source context from chunks in the topic's course by cosine distance.

```
TopicGroup     { id, slug, name, description }
Course         { id, slug, name }
Topic          { id, slug, title, summary, order, courseId, embedding(vector 1024), topicGroups (m2m) }
TopicEdge      { fromId, toId, kind, confidence, createdAt }
Block          { id, type, content, order, source, citation?, manually_edited, generation_metadata, group_id, topicId }
Chunk          { id, courseId, content, contentHash, sourcePath, sourceType, chunkIndex, pageNumber?, sectionPath?, tokenCount?, embedding(vector 1024) }
_TopicGroups   { A: Topic.id, B: TopicGroup.id }   # Prisma implicit m2m join
```

Row Level Security is enabled on all pipeline-written tables with public-read policies. Writes use the Supabase service role key and bypass RLS. Authenticated-admin write policies will be added with the admin auth layer.

---

## Verified state (multivariable-calculus)

- 16 local source files, 94 original local chunks
- 18 topics extracted, all linked to `math-foundations`
- Slugs stable across re-runs (anchored via prior-extraction lookup)
- All topic embeddings populated
- Agent 4 enrichment brought all topics above coverage threshold: no sparse topics and no thin topics under `strong>=0.75`, `strong_min=3`
- Generated block pages persisted for all 18 topics
- 1,054 generated blocks currently persisted
- 60 unique chunk IDs referenced by generated block provenance; all resolve to same-course chunks
- Provenance references include local `exams`, local `homework`, and Agent 4 `web` chunks
- 50 prerequisite edges; known-bad mapper edges from `scripts/drop_bad_edges.py` are excluded
- No cycles
- Transitive ancestor queries validated against manual calc-curriculum intuition (e.g. `mvc-lagrange-multipliers` correctly resolves to 7 ancestors across 2 depth levels)
- Mapper cost per run: ~$0.13
- Current Agent 3 prompt version: `agent3.v4`
- Current persisted block set: 18/18 topics, 1,058 blocks, all `agent3.v4`
- Latest full Agent 3 persisted run: one full MVC v4 pass completed topic-by-topic; `mvc-arc-length` failed validation once and then cleared on targeted rerun
- Latest judge prompt version: `judge.v4`
- Latest full judge report: `reports/judge_multivariable-calculus_20260531T204802Z.json`
- Latest judge status: 43 findings in the full report (20 high, 21 medium, 2 low), with all 18 topics parse-clean
- Dominant judge clusters: `missing_group` is down from 27 to 15; `missing_plot` is now mostly renderer-scope tension around geometry examples; factual findings still need human triage with citation footers visible
- Image block infrastructure is present (`BlockType.image`, block schema/types, renderer, `block-images` Supabase Storage bucket); Agent 3 validation rejects generated image blocks
- Topic pages render citation footers from `generation_metadata.source_chunk_ids`, joined to `Chunk`, so judge triage can see grounding sources without inline citation prose
- Final content-generation eval: all checks passing (`no_sparse_topics`, block schemas, source chunk IDs, pinned anchors, prereq cycles, known-bad edges)

---

## Numerical computation readout

Latest real run: 2026-06-01, using the `.env` Anthropic key by running commands with `env -u ANTHROPIC_API_KEY`.

Important operational note: the inherited shell environment had a stale Anthropic key that overrode `.env`. Use `env -u ANTHROPIC_API_KEY ...` for pipeline runs from this environment, or remove the stale parent env var.

Current status: content generated for all topics and content-generation evals pass.

- Source set: 22 homework PDFs plus `topics/Course Content.docx`
- 135 local chunks written
- 26 topics extracted; the structure still looks coherent: floating point, finite differences, interpolation/splines, quadrature, nonlinear solves, linear systems, least squares, ODEs, BVPs, and PDE finite differences
- Four thin-but-dense topics remain under `strong>=0.75`, `strong_min=3`: `number-base-conversion-floating-point`, `floating-point-error-propagation`, `loss-of-significance`, `fixed-point-iteration`
- Agent 4 found no curated URLs for those thin topics, but block generation succeeded; thinness is not currently the blocker
- 1,424 generated `agent3.v4` blocks persisted across all 26 topics
- 93 unique source chunk IDs referenced by generated block provenance; all resolve
- 63 prerequisite edges persisted, with no cycles
- Mapper needed manual false-positive exclusions for a floating-point peer edge and Matlab-tooling reverse edges; those are now in `pipeline.mapper.MANUAL_EXCLUDED_EDGES`
- Final eval log: `logs/numcomp-evals-20260531-final-with-coverage.log`
- Final judge report: `reports/judge_numerical-computation_20260601T014240Z.json`
- Judge status: 46 findings across 26 topics, with 19 `ok` topics and 7 `parse_failed` judge topics
- Judge clusters: 22 `missing_group`, 18 `factual_error`, 2 `generic_prose`, 2 `confusing_transition`, 1 `missing_plot`, 1 `broken_plot_spec`
- Factual judge quality is mixed: at least two high-severity factual findings explicitly self-refute by saying the generated content is correct

Readout decision:

1. Build `judge.v5` first. Reasons: 7 judge parse failures and recurring self-contradictory factual-error false positives make the report too noisy to drive content edits confidently.
2. Then tighten Agent 3 compliance. Reasons: `missing_group` is still the dominant real mechanical cluster, and both numerical computation and DSA exposed transient invalid `source_chunk_ids` during generation.
3. Defer admin-editor tooling for this course until judge.v5 separates real isolated content bugs from false positives.

---

## Data structures and algorithms readout

Latest run: 2026-06-01, started after the numerical-computation readout as the first algorithmic/code-adjacent contrast course.

Current status: generated for all topics and content-generation evals pass.

- Source set: 20 exam PDFs, 25 homework/recitation PDFs, 28 lecture PDFs, and `topics/Course Goals and Objectives.docx`
- 1,730 local chunks written
- 36 topics extracted, spanning asymptotics, divide-and-conquer, heaps/sorting/select, graphs, shortest paths, max flow, dynamic programming, greedy algorithms, MSTs, union-find, linear programming, and modeling
- Four thin-but-dense topics remain: `dsa-huffman-encoding`, `dsa-horn-formulas`, `dsa-set-cover`, `dsa-linear-programming`
- Agent 4 found no curated URLs for those thin topics; generated thin topics succeeded where attempted
- 74 prerequisite edges persisted, with no cycles
- Mapper needed manual exclusions for reverse/example edges around divide-and-conquer, max-flow/graph-modeling, and MST theory; those are now in `pipeline.mapper.MANUAL_EXCLUDED_EDGES`
- 1,691 generated `agent3.v4` blocks persisted across all 36 topics
- 181 unique source chunk IDs referenced by generated block provenance; all resolve
- Final eval log: `logs/dsa-evals-20260601-final.log`
- Final judge report: `reports/judge_data-structures-and-algorithms_20260601T035631Z.json`
- Judge status: 53 findings across 36 topics, with 35 `ok` topics and 1 `parse_failed` judge topic (`dsa-set-cover`)
- Judge clusters: 20 `missing_group`, 19 `factual_error`, 7 `confusing_transition`, 5 `generic_prose`, 2 `missing_plot`

DSA exposed repeated Agent 3 issues outside math-heavy courses:

- Malformed JSON on graph/DP topics before targeted retry (`dsa-scc`, `dsa-rna-secondary-structure`)
- Invalid `source_chunk_ids` before provenance filtering (`dsa-floyd-warshall`)
- Successful generation for pseudocode/complexity topics including MoMSelect, Strassen, graph basics, DFS/BFS, Dijkstra, Bellman-Ford, Floyd-Warshall, max flow, DP fundamentals, LIS/LCS, RNA folding, knapsack, Huffman, MSTs, union-find, LP, and graph modeling

Readout decision: DSA is healthy at the structural/eval layer, but not clean enough to justify broadening to operating systems or systems programming yet. Its judge profile matches numerical computation: judge parse/noise issues plus repeated Agent 3 grouping and content-precision findings. Do `judge.v5`, then an Agent 3 compliance pass, then rejudge numerical computation and DSA before adding the systems course.

---

## Next phase playbook

The next phase is about proving generalization one course at a time. Numerical computation and DSA are both healthy at the structural/eval layer, but both show judge/Agent 3 quality work before the next broadening step.

### 1. Tighten the judge, then Agent 3

Create `judge.v5` before making another broad content-editing pass. Numerical computation produced a useful full-course report, but 7/26 judge topics failed parse and several high-severity factual findings self-refuted. A noisy judge makes it too easy to spend effort on the wrong content fixes.

Judge v5 should focus on:

- Factual-error discipline: only flag a generated claim that is actually wrong.
- No source-only errors: if the source chunk has an error but the generated block does not repeat it, do not flag the block.
- No self-contradictory findings: if the description says "this is correct", omit it.
- Better parse resilience for model outputs that are nearly JSON but wrapped in stray text.

Then create the next Agent 3 prompt/compliance pass. It should focus on:

- More aggressive grouping for display math plus immediate interpretation.
- More aggressive grouping for plot plus the paragraph that names features of that plot.
- Stronger source-ID discipline: use only IDs shown in `SOURCE CHUNKS`, and omit provenance rather than inventing or mutating IDs.
- Stronger JSON discipline for long code/pseudocode-heavy topics, especially graph algorithms and dynamic programming examples.
- Plotting concrete geometry examples when relevant, while staying within renderer reality.

Run after the next judge/Agent 3 pass:

```bash
env -u ANTHROPIC_API_KEY .venv/bin/python -m pipeline.evals.content_generation --course data-structures-and-algorithms
env -u ANTHROPIC_API_KEY CLAUDE_JUDGE_TIMEOUT=300 .venv/bin/python -m pipeline.judge --course data-structures-and-algorithms --pause-seconds 1
env -u ANTHROPIC_API_KEY .venv/bin/python -m pipeline.evals.content_generation --course numerical-computation
env -u ANTHROPIC_API_KEY CLAUDE_JUDGE_TIMEOUT=300 .venv/bin/python -m pipeline.judge --course numerical-computation --pause-seconds 1
```

Compare category counts across MVC, numerical computation, and DSA. Repeated categories across courses are prompt or renderer issues; isolated factual findings can wait for admin-editor fixes after judge.v5 is trustworthy.

### 2. Add image blocks after the MVC QA loop stabilizes

Status: done for the minimal infrastructure pass. Image blocks are admin-only and survive regeneration through the existing pinned-anchor path.

Implementation checklist:

- [x] Add `image` to the Prisma `BlockType` enum.
- [x] Add `image` to `pipeline/block_schema.py`.
- [x] Add `ImageBlock` to `types/blocks.ts`.
- [x] Shape: `props: { src: string, alt: string, caption?: string, width?: number }`, `content: []`.
- [x] Add a Supabase Storage bucket for uploaded images (`block-images`).
- [x] Add renderer support using `<figure>`, `<img>`, and optional `<figcaption>`.
- [x] Keep the model contract explicit: Agent 3 validation rejects generated `image`; only the admin/editor should create it.
- [x] Verify pinned image anchors through the reconciler-shape test; admin API should set `manually_edited=true` once it exists.

### 3. Add citation footers next

Status: done for topic pages. Citation footers pair naturally with judge triage because they expose which chunks grounded each generated topic.

Implementation checklist:

- [x] On topic pages, read `generation_metadata.source_chunk_ids` from rendered blocks.
- [x] Join those IDs against `Chunk`.
- [x] Deduplicate by `(sourcePath, pageNumber, sectionPath)` while preserving first block-order occurrence.
- [x] Render a compact footer at the bottom of the topic page.
- [x] Keep inline content citation-free; Agent 3 still never writes attribution prose.

This makes factual-error review faster: when the judge flags a block, the footer shows the source chunks the page was grounded in.

### 4. Add the next contrast course

After numerical computation completes cleanly, add `data-structures-and-algorithms` next. It is the best contrast without jumping straight into capstone or technical-writing material: algorithmic, code-adjacent, conceptually structured, and likely to expose whether Agent 3 handles examples, pseudocode, complexity, and prerequisite mapping outside math-heavy courses.

Recommended order:

1. **Numerical Computation**: finish the blocked end-to-end run and treat it as the real generalization readout.
2. **Data Structures and Algorithms**: next contrast course after numerical computation is healthy.
3. **Operating Systems** or **Systems Programming**: broadening step if both numerical computation and DSA look healthy, to test lower-level systems content.

Course shakedown:

```bash
# 1. Put files under the course folder.
mkdir -p /Volumes/AIStack/modules/knowledge/docs/<course-name>/{lectures,exams,homework,reference}

# 2. Run the full pipeline.
python3 -m pipeline.course_orchestrator --course <course-name> --include-thin

# 3. Inspect topic extraction and graph shape before judging content.
python3 -m scripts.query_prereqs <one-important-topic-slug>

# 4. Run mechanical evals.
python3 -m pipeline.evals.content_generation --course <course-name>

# 5. Judge the generated content.
python3 -m pipeline.judge --course <course-name> --pause-seconds 1
```

What to look for:

- Topic count: wildly too many or too few topics means extractor prompt/course chunking needs work.
- Group assignment: a course should land in broad groups, not create a course-shaped group by accident.
- Prereq graph: no cycles, no obvious future topic as prerequisite of an earlier one.
- Sparse topics: enrich before generating if coverage is weak.
- Judge clusters: repeated categories across courses are prompt or renderer issues; isolated findings are future admin edits.

Move on from MVC when the remaining high/medium findings are either clearly false positives or below roughly five real issues across the course. If another regen barely improves the category counts, stop iterating and let the future admin editor handle isolated content edits.

---

## Website

### Public routes

| Route                       | Description                                  |
| --------------------------- | -------------------------------------------- |
| `/`                         | Homepage, browse topic groups                |
| `/[group]`                  | All courses in a topic group                 |
| `/[group]/[course]`         | All topics in a course                       |
| `/[group]/[course]/[topic]` | Topic page, renders blocks in learning order |

### Admin routes (login required)

| Route                     | Description                            |
| ------------------------- | -------------------------------------- |
| `/admin`                  | Dashboard                              |
| `/admin/editor/[topicId]` | BlockNote editor for a topic's blocks  |
| `/admin/upload`           | Phase 2: trigger pipeline from browser |

Admin routes are protected by Next.js middleware. Unauthenticated requests redirect to `/login`.

Block types: `paragraph`, `heading`, `bulletListItem`, `numberedListItem`, `codeBlock`, `callout`, `math`, `plot`

---

## Workflow

### Add a new course

```bash
# 1. Drop files onto AIStack
mkdir -p /Volumes/AIStack/modules/knowledge/docs/<course-name>/{lectures,exams,homework}
cp ~/Downloads/*.pdf /Volumes/AIStack/modules/knowledge/docs/<course-name>/lectures/

# 2. Run the course pipeline
cd ~/code/the-library-of-vincandria
python3 -m pipeline.course_orchestrator --course <course-name> --include-thin
```

### Add files to an existing course

```bash
cp ~/Downloads/new-lecture.pdf /Volumes/AIStack/modules/knowledge/docs/<course-name>/lectures/
python3 -m pipeline.course_orchestrator --course <course-name> --include-thin
```

The extractor treats its chunk set as authoritative, so use a full-course rerun after adding material. Single-file chunking is useful for inspection, not for safe course reconciliation.

### Regenerate a course

```bash
python3 -m pipeline.course_orchestrator --course <course-name> --include-thin
```

The old `pipeline.ingest` wrapper is not present yet. `db.reset_course(course_id)` exists as a lower-level helper for clearing non-manual blocks, but there is no public reset CLI at the moment.

### Run individual agents

```bash
# Chunk only
python3 -m pipeline.chunker --course <course-name> --out /tmp/chunks.json

# Extract topics (dry run prints JSON without writing)
python3 -m pipeline.extractor --course <course-name> --chunks /tmp/chunks.json --dry-run
python3 -m pipeline.extractor --course <course-name> --chunks /tmp/chunks.json

# Build prerequisite graph
python3 -m pipeline.mapper <course-name> --dry-run
python3 -m pipeline.mapper <course-name>

# Enrich sparse/thin topics with allow-listed web chunks
python3 -m pipeline.enricher --course <course-name> --dry-run
python3 -m pipeline.enricher --course <course-name> --include-thin

# Generate teaching blocks
python3 -m pipeline.block_gen --course <course-name> --dry-run --json
python3 -m pipeline.block_gen --course <course-name> --json --pause-seconds 75

# Judge generated content
python3 -m pipeline.judge --course <course-name> --pause-seconds 1

# Run the full course pipeline
python3 -m pipeline.course_orchestrator --course <course-name> --dry-run --include-thin
python3 -m pipeline.course_orchestrator --course <course-name> --include-thin

# Inspect the graph
python3 -m scripts.query_prereqs <topic-slug>

# Apply known eval-grade edge fixes (one-off, idempotent)
python3 -m scripts.drop_bad_edges

# Run content-generation evals
python3 -m pipeline.evals.content_generation --course <course-name>
```

---

## Setup

### Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install anthropic voyageai ollama pymupdf python-docx python-pptx openpyxl nbformat \
            python-dotenv psycopg2-binary
```

### Node

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Prisma

```bash
npx prisma generate       # generate client after schema changes
npx prisma db push        # push schema to Supabase
npx prisma studio         # browse data locally
```

### Environment variables

Create `.env` at the project root. Never commit it; `.gitignore` includes `.env`.

```
# Database (Supabase)
DATABASE_URL=
DIRECT_URL=
SUPABASE_SERVICE_ROLE_KEY=

# Anthropic
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-6

# Optional pricing override (USD per million tokens)
CLAUDE_PRICE_INPUT=3.00
CLAUDE_PRICE_OUTPUT=15.00

# Voyage (embeddings)
VOYAGE_API_KEY=

# AIStack paths
AISTACK_DOCS=/Volumes/AIStack/modules/knowledge/docs

# Ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3

# Auth
NEXTAUTH_SECRET=        # generate with: openssl rand -base64 32
NEXTAUTH_URL=http://localhost:3000
```

`KUZU_PATH` is no longer used. Remove from any existing `.env`.

---

## Supported file types

| Type                   | Parser      |
| ---------------------- | ----------- |
| PDF                    | pymupdf     |
| DOCX                   | python-docx |
| PPTX                   | python-pptx |
| XLSX                   | openpyxl    |
| IPYNB                  | nbformat    |
| .c .py .v .js .ts etc. | raw + tag   |

---

## Build order

1. ~~`prisma/schema.prisma`~~ done
2. ~~`pipeline/chunker.py`~~ done, validated on multivariable-calculus (94 chunks, 16 files)
3. ~~`pipeline/extractor.py`~~ done, validated on multivariable-calculus (18 topics, clean group assignment, slug stability)
4. ~~`pipeline/mapper.py`~~ done, validated on multivariable-calculus (50 edges, no cycles, transitive queries correct)
5. ~~`pipeline/enricher.py`~~ done, v1 allow-listed web chunks for sparse/thin topics
6. ~~`pipeline/block_gen.py` + `pipeline/orchestrator.py`~~ done, validated and persisted across multivariable-calculus
7. ~~`pipeline/course_orchestrator.py`~~ done, aggregates status/token/cost across agents
8. ~~`pipeline/evals/`~~ done, seeded with the 4 forbidden edges from `drop_bad_edges.py`
9. Public website render from populated database
10. Admin dashboard BlockNote editor wired to blocks table with `manually_edited` flag
11. Phase 2 upload UI trigger pipeline from browser
