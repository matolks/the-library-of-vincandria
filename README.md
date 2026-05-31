# The Library of Vincandira

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
| Agent 3 — Block Generator          | Next        |
| Agent 4 — Web Enricher             | Deferred    |
| `ingest.py` orchestrator           | Not started |
| Eval harness (`pipeline/evals/`)   | Not started |
| Public website                     | Not started |
| Admin dashboard + BlockNote editor | Not started |

---

## How it works

```
AIStack (your drive)           This repo                        Public
/modules/knowledge/docs/  →   pipeline/ parses + processes  →  website renders
      course files              writes to Supabase               from database
```

You drop files onto the drive and run one command. The pipeline runs in two stages:

**Stage 1, Local (Ollama).** Reads every file, extracts raw text, and chunks it into clean passages. Tags chunks with `source_type` (lectures, exams, homework, reference, topics) inferred from the folder structure. No API calls. Nothing leaves your machine.

**Stage 2, Claude API.** Agents run in sequence on the chunked text: extract topics and assign them to broad groups, map dependencies between topics, generate teaching blocks for each topic. Results write to Supabase. Both topics and the prerequisite graph live in Postgres (the graph as a `TopicEdge` table queried via recursive CTEs). The website reflects changes immediately.

When you add new material, drop the files in and run the command again. The pipeline is idempotent. It upserts existing records rather than duplicating them. Blocks you have manually edited in the admin are flagged and skipped on re-ingestion.

---

## Model split

| Task                                    | Model                          | Why                                                                               |
| --------------------------------------- | ------------------------------ | --------------------------------------------------------------------------------- |
| File parsing, text extraction, chunking | Ollama (local)                 | Deterministic, high-volume, no reasoning needed. Data stays local.                |
| Topic embeddings (1024-dim)             | Voyage `voyage-3.5-lite` (API) | Strong retrieval quality at low cost. Used by the mapper for candidate retrieval. |
| Topic extraction + group assignment     | Claude API                     | Requires consistent structured JSON output across varied content.                 |
| Dependency mapping                      | Claude API                     | Requires cross-topic directional reasoning.                                       |
| Block generation (teaching content)     | Claude API                     | Teaching quality depends on reasoning depth.                                      |
| Web enrichment (deferred)               | Claude API                     | Refines blocks against external sources with citations.                           |

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
the-library-of-vincandira/
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
│   ├── ingest.py                  # entry point, orchestrates all stages (not yet built)
│   ├── chunker.py                 # Ollama: parse files, extract text, chunk
│   ├── embeddings.py              # Voyage embeddings (1024-dim, batched)
│   ├── extractor.py               # Claude Agent 1: topics + group assignment
│   ├── mapper.py                  # Claude Agent 2: prereq graph → Postgres TopicEdge
│   ├── block_gen.py               # Claude Agent 3: generate teaching blocks (not yet built)
│   ├── enricher.py                # Claude Agent 4: web-sourced refinement (deferred)
│   ├── parsers/
│   │   ├── pdf.py                 # pymupdf
│   │   ├── docx.py                # python-docx
│   │   ├── xlsx.py                # openpyxl
│   │   ├── pptx.py                # python-pptx
│   │   ├── ipynb.py               # nbformat
│   │   └── code.py                # raw text + language tag
│   ├── db.py                      # Supabase write client + pgvector retrieval
│   └── evals/                     # ground truth + eval scripts (not yet built)
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

**Agent 3, Block Generator** (`pipeline/block_gen.py`, not yet built)

Takes one topic at a time. Returns page blocks ordered the way a professor would teach it: concept definition first, example or worked problem second, key insight last. Skips any block with `manually_edited: true`. Every block is tagged with a `source` (`local`, `web`, `manual`, or `generated`) and optional `citation`.

```json
{
  "blocks": [
    {
      "type": "text",
      "order": 1,
      "source": "local",
      "content": "The Fourier Transform decomposes a time-domain signal..."
    },
    {
      "type": "code",
      "order": 2,
      "language": "math",
      "source": "local",
      "content": "X(f) = ∫ x(t)e^{-j2πft} dt"
    },
    {
      "type": "callout",
      "order": 3,
      "source": "generated",
      "content": "Multiplication in frequency = convolution in time."
    }
  ]
}
```

**Agent 4, Enricher** (`pipeline/enricher.py`, deferred)

Refines existing blocks against external sources. Adds new blocks with `source: "web"` and a citation URL. Respects `manually_edited`.

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

The `manually_edited` flag on `Block` is critical. When re-ingestion runs, any block with this flag set to `true` is skipped. This is what lets you edit content in the admin without the pipeline overwriting your work. Any block edited through the admin API has this set automatically.

`Block.source` records provenance (`local`, `web`, `manual`, `generated`) and `Block.citation` holds an optional URL for web-sourced content.

`Topic.embedding` is a 1024-dim `vector` column with an HNSW index, populated by Voyage during extraction and queried by the mapper via cosine distance (`<=>`).

```
TopicGroup     { id, slug, name, description }
Course         { id, slug, name }
Topic          { id, slug, title, summary, order, courseId, embedding(vector 1024), topicGroups (m2m) }
TopicEdge      { fromId, toId, kind, confidence, createdAt }
Block          { id, type, content, order, language?, source, citation?, manually_edited, topicId }
_TopicGroups   { A: Topic.id, B: TopicGroup.id }   # Prisma implicit m2m join
```

Row Level Security is enabled on all pipeline-written tables with public-read policies. Writes use the Supabase service role key and bypass RLS. Authenticated-admin write policies will be added with the admin auth layer.

---

## Verified state (multivariable-calculus)

- 16 source files, 94 chunks
- 18 topics extracted, all linked to `math-foundations`
- Slugs stable across re-runs (anchored via prior-extraction lookup)
- All topic embeddings populated
- 50 prerequisite edges (53 generated, 3 manually dropped as known false positives)
- No cycles
- Transitive ancestor queries validated against manual calc-curriculum intuition (e.g. `mvc-lagrange-multipliers` correctly resolves to 7 ancestors across 2 depth levels)
- Mapper cost per run: ~$0.13

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

Block types: `text`, `code`, `image`, `callout`, `graph`

---

## Workflow

### Add a new course

```bash
# 1. Drop files onto AIStack
mkdir -p /Volumes/AIStack/modules/knowledge/docs/<course-name>/{lectures,exams,homework}
cp ~/Downloads/*.pdf /Volumes/AIStack/modules/knowledge/docs/<course-name>/lectures/

# 2. Run the pipeline (once ingest.py exists)
cd ~/code/the-library-of-vincandira
python3 -m pipeline.ingest --course <course-name>
```

### Add files to an existing course

```bash
cp ~/Downloads/new-lecture.pdf /Volumes/AIStack/modules/knowledge/docs/<course-name>/lectures/
python3 -m pipeline.ingest --course <course-name> --file new-lecture.pdf
```

### Reset and re-ingest a course

```bash
python3 -m pipeline.ingest --course <course-name> --reset
```

`--reset` clears all blocks for the course that do not have `manually_edited: true`.

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

# Inspect the graph
python3 -m scripts.query_prereqs <topic-slug>

# Apply known eval-grade edge fixes (one-off, idempotent)
python3 -m scripts.drop_bad_edges
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
CLAUDE_MODEL=claude-sonnet-4-5-20250929

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
5. `pipeline/block_gen.py` next focus
6. `pipeline/ingest.py` orchestrator, aggregates token/cost across agents
7. `pipeline/evals/` formalize eval harness; seed with the 4 forbidden edges from `drop_bad_edges.py`
8. Public website render from populated database
9. Admin dashboard BlockNote editor wired to blocks table with `manually_edited` flag
10. `pipeline/enricher.py` web enrichment with citations
11. Phase 2 upload UI trigger pipeline from browser
