"""
Agent 4: allow-listed web enrichment for sparse/thin topics.

Fetches curated web sources, caches raw responses, extracts readable text,
chunks, embeds, and upserts the result as `Chunk` rows with sourceType='web'.
block_gen then consumes those rows through the existing retrieval path.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urlparse
from urllib.request import Request, urlopen

from pipeline.block_gen import get_topic_context
from pipeline.chunker import chunk_text


CACHE_DIR = Path(".cache/agent4")
USER_AGENT = "the-library-of-vincandria-agent4/1.0"

WEAK_FLOOR = 0.70
STRONG_FLOOR = 0.75
THIN_STRONG_CHUNKS = 3
DEFAULT_MAX_FETCHES_PER_TOPIC = 5

ALLOWED_EXACT_HOSTS = {
    "en.wikipedia.org",
    "ocw.mit.edu",
    "mathworld.wolfram.com",
    "openstax.org",
    "tutorial.math.lamar.edu",
    "www.khanacademy.org",
    "khanacademy.org",
}

ALLOWED_SUFFIXES = (".edu",)

CURATED_URLS: dict[str, tuple[str, ...]] = {
    "mvc-lagrange-multipliers": (
        "https://en.wikipedia.org/wiki/Lagrange_multiplier",
        "https://mathworld.wolfram.com/LagrangeMultiplier.html",
        "https://openstax.org/books/calculus-volume-3/pages/4-8-lagrange-multipliers",
        "https://ocw.mit.edu/courses/18-02sc-multivariable-calculus-fall-2010/pages/2.-partial-derivatives/part-c-lagrange-multipliers-and-constrained-differentials/",
    ),
    "mvc-double-integrals": (
        "https://en.wikipedia.org/wiki/Multiple_integral",
        "https://mathworld.wolfram.com/DoubleIntegral.html",
        "https://openstax.org/books/calculus-volume-3/pages/5-1-double-integrals-over-rectangular-regions",
        "https://openstax.org/books/calculus-volume-3/pages/5-2-double-integrals-over-general-regions",
    ),
}


@dataclass(frozen=True)
class TopicCoverage:
    topic_id: str
    slug: str
    top_similarity: float
    strong_chunks: int
    status: str  # "dense" | "thin" | "sparse"


@dataclass(frozen=True)
class EnrichmentResult:
    topic_id: str
    slug: str
    status: str  # "ok" | "no_sources" | "fetch_failed" | "dry_run"
    urls_fetched: int
    chunks_written: int
    before_top_similarity: float
    after_top_similarity: float
    coverage_before: str
    coverage_after: str
    input_tokens: int = 0
    output_tokens: int = 0
    usd_cost: float = 0.0
    errors: tuple[str, ...] = ()


def enrich_topic(
    topic_id: str,
    *,
    urls: Iterable[str] | None = None,
    max_fetches: int = DEFAULT_MAX_FETCHES_PER_TOPIC,
    dry_run: bool = False,
    cache_dir: Path = CACHE_DIR,
    pause_seconds: float = 0.25,
) -> EnrichmentResult:
    """Run Agent 4 for one topic and return structured status."""
    before = get_topic_context(topic_id, chunk_similarity_floor=WEAK_FLOOR)
    selected_urls = list(urls or CURATED_URLS.get(before.topic.slug, ()))
    selected_urls = [_canonicalize_url(u) for u in selected_urls]
    selected_urls = selected_urls[:max_fetches]

    if not selected_urls:
        return EnrichmentResult(
            topic_id=topic_id,
            slug=before.topic.slug,
            status="no_sources",
            urls_fetched=0,
            chunks_written=0,
            before_top_similarity=before.top_similarity,
            after_top_similarity=before.top_similarity,
            coverage_before=before.coverage,
            coverage_after=before.coverage,
            errors=("no curated or explicit URLs for topic",),
        )

    errors: list[str] = []
    pages: list[_FetchedPage] = []
    for url in selected_urls:
        try:
            _assert_allowed_url(url)
            pages.append(_fetch_page(url, cache_dir=cache_dir))
            time.sleep(pause_seconds)
        except (ValueError, HTTPError, URLError, TimeoutError, OSError) as e:
            errors.append(f"{url}: {e}")

    if not pages:
        return EnrichmentResult(
            topic_id=topic_id,
            slug=before.topic.slug,
            status="fetch_failed",
            urls_fetched=0,
            chunks_written=0,
            before_top_similarity=before.top_similarity,
            after_top_similarity=before.top_similarity,
            coverage_before=before.coverage,
            coverage_after=before.coverage,
            errors=tuple(errors),
        )

    records = _pages_to_records(before.topic.title, before.topic.slug, pages)
    if dry_run:
        return EnrichmentResult(
            topic_id=topic_id,
            slug=before.topic.slug,
            status="dry_run",
            urls_fetched=len(pages),
            chunks_written=len(records),
            before_top_similarity=before.top_similarity,
            after_top_similarity=before.top_similarity,
            coverage_before=before.coverage,
            coverage_after=before.coverage,
            errors=tuple(errors),
        )

    _embed_and_upsert(before.topic.course_slug, records)
    after = get_topic_context(topic_id, chunk_similarity_floor=WEAK_FLOOR)

    return EnrichmentResult(
        topic_id=topic_id,
        slug=before.topic.slug,
        status="ok",
        urls_fetched=len(pages),
        chunks_written=len(records),
        before_top_similarity=before.top_similarity,
        after_top_similarity=after.top_similarity,
        coverage_before=before.coverage,
        coverage_after=after.coverage,
        errors=tuple(errors),
    )


def enrich_course(
    course_slug: str,
    *,
    topic_slug: str | None = None,
    include_thin: bool = False,
    max_fetches_per_topic: int = DEFAULT_MAX_FETCHES_PER_TOPIC,
    dry_run: bool = False,
) -> list[EnrichmentResult]:
    """Enrich sparse topics in a course; optionally include thin topics."""
    targets = _select_targets(course_slug, topic_slug, include_thin)
    return [
        enrich_topic(
            cov.topic_id,
            max_fetches=max_fetches_per_topic,
            dry_run=dry_run,
        )
        for cov in targets
    ]


def _select_targets(
    course_slug: str, topic_slug: str | None, include_thin: bool
) -> list[TopicCoverage]:
    from pipeline import db

    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.slug
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
              AND (%s::text IS NULL OR t.slug = %s)
            ORDER BY t."order"
            """,
            (course_slug, topic_slug, topic_slug),
        )
        rows = cur.fetchall()
    if not rows:
        raise SystemExit(f"No matching topics in course {course_slug!r}")

    out: list[TopicCoverage] = []
    for topic_id, slug in rows:
        chunks = db.top_chunks_for_topic(topic_id, k=8)
        sims = [1.0 - float(c["distance"]) for c in chunks]
        top = max(sims, default=0.0)
        strong = sum(1 for s in sims if s >= STRONG_FLOOR)
        if top < WEAK_FLOOR:
            status = "sparse"
        elif strong < THIN_STRONG_CHUNKS:
            status = "thin"
        else:
            status = "dense"
        if topic_slug or status == "sparse" or (include_thin and status == "thin"):
            out.append(TopicCoverage(topic_id, slug, top, strong, status))
    return out


@dataclass(frozen=True)
class _FetchedPage:
    url: str
    title: str
    text: str


def _canonicalize_url(url: str) -> str:
    clean, _fragment = urldefrag(url.strip())
    return clean


def _assert_allowed_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("only https URLs are allowed")
    host = (parsed.hostname or "").lower()
    if host in ALLOWED_EXACT_HOSTS:
        return
    if any(host.endswith(suffix) for suffix in ALLOWED_SUFFIXES):
        return
    raise ValueError(f"host {host!r} is not in the Agent 4 allow-list")


def _fetch_page(url: str, *, cache_dir: Path) -> _FetchedPage:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    meta_path = cache_dir / f"{key}.json"
    body_path = cache_dir / f"{key}.body"

    if meta_path.exists() and body_path.exists():
        meta = json.loads(meta_path.read_text())
        raw = body_path.read_bytes()
        content_type = meta.get("content_type", "text/html")
    else:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20, context=_ssl_context()) as resp:
            content_type = resp.headers.get("content-type", "text/html")
            raw = resp.read(2_000_000)
        body_path.write_bytes(raw)
        meta_path.write_text(
            json.dumps({"url": url, "content_type": content_type}, indent=2)
        )

    if "html" not in content_type:
        raise ValueError(f"unsupported content type for v1: {content_type}")

    decoded = raw.decode("utf-8", errors="replace")
    title, text = _html_to_text(decoded)
    if len(text.split()) < 80:
        raise ValueError("extracted page text is too short")
    return _FetchedPage(url=url, title=title or _domain(url), text=text)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        else:
            self.parts.append(text)


def _html_to_text(raw_html: str) -> tuple[str, str]:
    parser = _ReadableHTMLParser()
    parser.feed(raw_html)
    joined = " ".join(parser.parts)
    joined = re.sub(r"\s+", " ", joined)
    joined = re.sub(r"(\.|\?|!)\s+", r"\1\n", joined)
    return parser.title.strip(), joined.strip()


def _pages_to_records(topic_title: str, topic_slug: str, pages: list[_FetchedPage]):
    from pipeline import db

    records: list[db.ChunkRecord] = []
    for page in pages:
        topic_prefix = (
            f"Topic: {topic_title} ({topic_slug})\n"
            f"Web source: {page.title}\n"
            f"URL: {page.url}\n\n"
        )
        for idx, text in enumerate(chunk_text(page.text, chunk_size=320, overlap=45)):
            content = f"{topic_prefix}{text}".replace("\x00", "").strip()
            if len(content.split()) < 40:
                continue
            records.append(
                db.ChunkRecord(
                    content=content,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    source_path=page.url,
                    source_type="web",
                    chunk_index=idx,
                    page_number=None,
                    section_path=page.title,
                    token_count=len(content.split()),
                )
            )
    return records


def _embed_and_upsert(course_slug: str, records) -> int:
    from pipeline import db
    from pipeline.embeddings import embed_documents

    course_id = db.get_course_id(course_slug)
    if course_id is None:
        raise ValueError(f"Course not found: {course_slug}")
    vectors = embed_documents([r.content for r in records])
    for record, vector in zip(records, vectors):
        record.embedding = vector
    return db.upsert_chunks(course_id, records)


def _domain(url: str) -> str:
    return urlparse(url).hostname or url


def _print_result(result: EnrichmentResult) -> None:
    print(json.dumps(asdict(result), sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Agent 4 web enrichment.")
    parser.add_argument("--course", required=True)
    parser.add_argument("--topic", help="optional topic slug; overrides sparse queue")
    parser.add_argument("--include-thin", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-fetches-per-topic", type=int, default=DEFAULT_MAX_FETCHES_PER_TOPIC)
    args = parser.parse_args()

    try:
        for result in enrich_course(
            args.course,
            topic_slug=args.topic,
            include_thin=args.include_thin,
            max_fetches_per_topic=args.max_fetches_per_topic,
            dry_run=args.dry_run,
        ):
            _print_result(result)
    finally:
        from pipeline import db

        db.close()


if __name__ == "__main__":
    main()
