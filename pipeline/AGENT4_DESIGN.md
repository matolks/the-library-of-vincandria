# Agent 4 Design — Web Enrichment

## Locked Contract

Agent 4 runs after mapper and before block generation:

`extractor -> mapper -> enricher -> block_gen`

Its only durable output is additional `Chunk` rows. Agent 3 keeps reading the
same `top_chunks_for_topic` retrieval path and does not receive a separate web
context channel.

## Storage Shape

Web enrichment upserts into `Chunk` using the same idempotency key as local
chunks: `(courseId, sourcePath, chunkIndex)`.

- `sourceType`: `web`
- `sourcePath`: canonical allow-listed URL
- `pageNumber`: `NULL`
- `sectionPath`: nearest heading/title when known
- `contentHash`: SHA-256 of the normalized chunk text
- `embedding`: Voyage document embedding for the normalized chunk text

The v1 schema has no `web_metadata` column. Citation rendering derives domain
and title from `sourcePath`/chunk text until that column is added.

## Source Policy

Fetching is allow-list only. A URL is refused before network I/O unless its host
matches one of these domains:

- `wikipedia.org`
- `ocw.mit.edu`
- `mathworld.wolfram.com`
- `openstax.org`
- `tutorial.math.lamar.edu`
- `.edu` hosts
- `khanacademy.org`

Forbidden classes remain forbidden even if a URL is manually supplied:
textbooks, homework-answer sites, auth-walled pages, paywalled pages, and
copyright aggregators. V1 enforces this by not including those domains in the
allow-list.

## Fetch, Cache, Chunk, Embed, Upsert Flow

1. Select candidate URLs from a curated per-topic catalog or explicit CLI URLs.
2. Canonicalize and allow-list the URL.
3. Read from the local cache when present; otherwise fetch with a small timeout
   and write the raw response under `.cache/agent4/`.
4. Extract readable text from HTML. PDF/source-specific extractors are deferred.
5. Prefix each chunk with the topic title/slug and source title so topic
   retrieval can select the right web chunks from the shared course chunk table.
6. Chunk with the existing `chunk_text` helper.
7. Embed chunks with Voyage using the existing document embedding path.
8. Upsert `ChunkRecord` rows with `sourceType='web'`.
9. Re-read topic coverage using `get_topic_context`; success means sparse topics
   now clear the weak floor.

## Queue Semantics

Default mode enriches only sparse topics (`top_similarity < 0.70`). Passing
`--include-thin` also enriches topics with fewer than three chunks above the
strong floor (`0.75`). Passing `--topic` is a manual override and runs that topic
whether or not it is currently sparse.

## V1 Seed Catalog

The sparse multivariable-calculus topics use these first:

- `mvc-lagrange-multipliers`
  - <https://en.wikipedia.org/wiki/Lagrange_multiplier>
  - <https://mathworld.wolfram.com/LagrangeMultiplier.html>
  - <https://openstax.org/books/calculus-volume-3/pages/4-8-lagrange-multipliers>
  - <https://ocw.mit.edu/courses/18-02sc-multivariable-calculus-fall-2010/pages/2.-partial-derivatives/part-c-lagrange-multipliers-and-constrained-differentials/>
- `mvc-double-integrals`
  - <https://en.wikipedia.org/wiki/Multiple_integral>
  - <https://mathworld.wolfram.com/DoubleIntegral.html>
  - <https://openstax.org/books/calculus-volume-3/pages/5-1-double-integrals-over-rectangular-regions>
  - <https://openstax.org/books/calculus-volume-3/pages/5-2-double-integrals-over-general-regions>

Search-then-fetch is deferred; the curated catalog is the safety boundary for v1.
