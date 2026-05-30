# The Library of Vincandira

A personal knowledge graph that transforms raw university course materials into a structured, publicly browsable website. A local Ollama model parses and chunks your files. Claude API agents extract concepts, map relationships, and generate teaching content. You refine everything through an admin block editor.

This is the first module running on AIStack — a local AI platform designed to support multiple independent projects. Future modules plug into the same platform without touching this codebase.

**Live site:** `[url when deployed]`
**Local platform:** AIStack — `/Volumes/AIStack/modules/knowledge/`

---

## How it works

```
AIStack (your drive)           This repo                        Public
/modules/knowledge/docs/  →   pipeline/ parses + processes  →  website renders
      course files              writes to Supabase               from database
```

You drop files onto the drive and run one command. The pipeline runs in two stages:

**Stage 1 — Local (Ollama).** Reads every file, extracts raw text, and chunks it into clean passages. No API calls. Nothing leaves your machine.

**Stage 2 — Claude API.** Three agents run in sequence on the chunked text: extract topics and assign them to broad groups, map dependencies between topics, generate teaching blocks for each topic. Results write to Supabase. The website reflects changes immediately.

When you add new material, drop the files in and run the command again. The pipeline is idempotent — it updates existing records rather than duplicating them. Blocks you have manually edited in the admin are flagged and skipped on re-ingestion.

---

## Model split

| Task                                    | Model          | Why                                                                |
| --------------------------------------- | -------------- | ------------------------------------------------------------------ |
| File parsing, text extraction, chunking | Ollama (local) | Deterministic, high-volume, no reasoning needed. Data stays local. |
| Topic extraction + group assignment     | Claude API     | Requires consistent structured JSON output across varied content.  |
| Dependency mapping                      | Claude API     | Requires cross-topic reasoning.                                    |
| Block generation (teaching content)     | Claude API     | Teaching quality depends on reasoning depth.                       |

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
│   │       │   ├── lecture1.pdf
│   │       │   ├── midterm.pdf
│   │       │   └── malloc_lab.c
│   │       ├── signals-and-systems/
│   │       ├── calculus/
│   │       └── .../
│   ├── email/
│   └── .../
│
├── graphs/
│   └── course_graph/          # Kuzu graph DB (concept dependencies)
│
├── rag/
│   └── chroma/                # Chroma vector DB (text similarity)
│
├── ollama-models/
└── README.md
```

Course files are flat by course name only. The AI determines which broad topic groups each course belongs to from content — a course like Signals and Systems spans both Math Foundations and Signals and Networks, and the agent figures that out without you deciding upfront.

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
│   ├── ingest.py                  # entry point, orchestrates all stages
│   ├── chunker.py                 # Ollama: parse files, extract text, chunk
│   ├── extractor.py               # Claude Agent 1: topics + group assignment
│   ├── mapper.py                  # Claude Agent 2: dependency graph → Kuzu
│   ├── block_gen.py               # Claude Agent 3: generate teaching blocks
│   ├── parsers/
│   │   ├── pdf.py                 # pymupdf
│   │   ├── docx.py                # python-docx
│   │   ├── xlsx.py                # openpyxl
│   │   └── code.py                # raw text + language tag
│   └── db.py                      # Supabase write client
│
├── types/
├── AGENTS.md
├── CLAUDE.md
├── .env                           # never commit
└── README.md
```

---

## The pipeline

### Stage 1 — Chunker (Ollama, local)

`pipeline/chunker.py`

Reads each file through the appropriate parser, extracts raw text, and splits it into clean passages using a local Ollama model. No API calls made here.

```json
{
  "course": "signals-and-systems",
  "file": "lecture3.pdf",
  "chunks": [
    {
      "text": "The Fourier Transform decomposes a signal into its frequency components...",
      "page": 4
    }
  ]
}
```

### Stage 2 — Three Claude API agents

**Agent 1 — Extractor** (`pipeline/extractor.py`)

Takes chunked text per course. Returns topics with summaries, key concepts, and broad group assignments. One topic can belong to multiple groups. Groups are assigned by the model based on content — your predefined list is passed as a suggestion, not a constraint.

```json
{
  "course": "Signals and Systems",
  "topics": [
    {
      "title": "Fourier Transform",
      "summary": "Decomposes a signal into its frequency components.",
      "key_concepts": ["frequency domain", "convolution", "harmonics"],
      "groups": ["math-foundations", "signals-and-networks"],
      "order_in_course": 4
    }
  ]
}
```

**Agent 2 — Mapper** (`pipeline/mapper.py`)

Takes all topics for a course. Returns dependency links between them. Writes the relationship graph to Kuzu so the website can show learning paths.

```json
{
  "dependencies": [
    { "from": "Complex Numbers", "to": "Fourier Transform" },
    { "from": "Differential Equations", "to": "Fourier Transform" }
  ]
}
```

**Agent 3 — Block Generator** (`pipeline/block_gen.py`)

Takes one topic at a time. Returns page blocks ordered the way a professor would teach it: concept definition first, example or worked problem second, key insight last. Skips any block with `manually_edited: true`.

```json
{
  "blocks": [
    {
      "type": "text",
      "order": 1,
      "content": "The Fourier Transform decomposes a time-domain signal..."
    },
    {
      "type": "code",
      "order": 2,
      "content": "X(f) = ∫ x(t)e^{-j2πft} dt",
      "language": "math"
    },
    {
      "type": "callout",
      "order": 3,
      "content": "Multiplication in frequency = convolution in time."
    }
  ]
}
```

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

Three levels: `TopicGroup → Topic → Block`

The `manually_edited` flag on `Block` is critical. When re-ingestion runs, any block with this flag set to `true` is skipped. This is what lets you edit content in the admin without the pipeline overwriting your work. Any block edited through the admin API has this set automatically.

```
TopicGroup  { id, slug, name, description }
Topic       { id, slug, title, summary, order, topicGroupId, courseId }
Block       { id, type, content, order, topicId, manually_edited, language? }
```

Define `prisma/schema.prisma` before writing any pipeline or API code. Everything is downstream of this.

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
mkdir -p /Volumes/AIStack/modules/knowledge/docs/<course-name>/
cp ~/Downloads/*.pdf /Volumes/AIStack/modules/knowledge/docs/<course-name>/

# 2. Run the pipeline
cd ~/code/library-of-vincandira
python3 pipeline/ingest.py --course <course-name>

# 3. Done
```

### Add files to an existing course

```bash
cp ~/Downloads/new-lecture.pdf /Volumes/AIStack/modules/knowledge/docs/<course-name>/
python3 pipeline/ingest.py --course <course-name> --file new-lecture.pdf
```

### Reset and re-ingest a course

```bash
python3 pipeline/ingest.py --course <course-name> --reset
```

`--reset` clears all blocks for the course that do not have `manually_edited: true`.

---

## Setup

### Python

```bash
pip install anthropic ollama pymupdf python-docx openpyxl python-dotenv kuzu psycopg2-binary
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

Create `.env` at the project root. Never commit it — make sure `.gitignore` includes `.env` before your first push.

```
# Database (Supabase)
DATABASE_URL=

# Anthropic
ANTHROPIC_API_KEY=

# AIStack paths
AISTACK_DOCS=/Volumes/AIStack/modules/knowledge/docs
KUZU_PATH=/Volumes/AIStack/graphs/course_graph

# Ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3

# Auth
NEXTAUTH_SECRET=        # generate with: openssl rand -base64 32
NEXTAUTH_URL=http://localhost:3000
```

---

## Supported file types

| Type              | Parser                  |
| ----------------- | ----------------------- |
| PDF               | pymupdf                 |
| DOCX              | python-docx             |
| XLSX              | openpyxl                |
| .c .py .v .js .ts | raw text + language tag |

---

## Build order

1. `prisma/schema.prisma` — define schema first, everything is downstream
2. `pipeline/chunker.py` — validate local Ollama parsing against one course
3. `pipeline/extractor.py` — validate Claude topic extraction output quality
4. `pipeline/mapper.py` + `pipeline/block_gen.py` — complete the pipeline
5. Public website — render from populated database
6. Admin dashboard — BlockNote editor wired to blocks table with `manually_edited` flag
7. Phase 2 upload UI — trigger pipeline from browser
