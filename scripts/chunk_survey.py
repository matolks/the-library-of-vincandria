"""
scripts/chunk_survey.py

Diagnostics for chunk-retrieval coverage. Three subcommands:

  survey   per-topic similarity distribution across a course
  grep     find chunks whose content matches a keyword
  show     dump one chunk's full content by id

All read-only. Uses the shared connection from pipeline.db.
"""
from __future__ import annotations

import argparse
import statistics
import sys

from pipeline import db


# ---- survey ---------------------------------------------------------------

def cmd_survey(course_slug: str, k: int, strong_floor: float, weak_floor: float) -> None:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.slug
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
            ORDER BY t."order"
            """,
            (course_slug,),
        )
        topics = cur.fetchall()

    if not topics:
        raise SystemExit(f"No topics in course {course_slug!r}")

    print(f"course={course_slug}  k={k}  strong>={strong_floor}  weak<{weak_floor}")
    print(f"{'slug':<48}  {'top':>6}  {'mean':>6}  {'>=floor':>8}  {'flag'}")
    print("-" * 84)

    sparse: list[tuple[str, float]] = []
    thin: list[tuple[str, float, int]] = []
    no_embed: list[str] = []

    for topic_id, slug in topics:
        try:
            rows = db.top_chunks_for_topic(topic_id, k=k)
        except ValueError as e:
            if "no embedding" in str(e):
                no_embed.append(slug)
                print(f"{slug:<48}  {'—':>6}  {'—':>6}  {'—':>8}  NO EMBED")
                continue
            raise
        if not rows:
            print(f"{slug:<48}  {'—':>6}  {'—':>6}  {'—':>8}  NO CHUNKS")
            continue
        sims = [1.0 - float(r["distance"]) for r in rows]
        top = max(sims)
        mean = statistics.mean(sims)
        strong = sum(1 for s in sims if s >= strong_floor)
        flag = ""
        if top < weak_floor:
            flag = "SPARSE"
            sparse.append((slug, top))
        elif strong < 3:
            flag = "thin"
            thin.append((slug, top, strong))
        print(f"{slug:<48}  {top:>6.3f}  {mean:>6.3f}  {strong:>8}  {flag}")

    print()
    if sparse:
        print(f"SPARSE ({len(sparse)}): top similarity below weak_floor={weak_floor}")
        for slug, top in sparse:
            print(f"  {slug:<48}  top={top:.3f}")
    if thin:
        print(f"thin ({len(thin)}): <3 chunks above strong_floor={strong_floor}")
        for slug, top, strong in thin:
            print(f"  {slug:<48}  top={top:.3f}  strong={strong}")
    if no_embed:
        print(f"NO EMBED ({len(no_embed)}): topics without embeddings")
        for slug in no_embed:
            print(f"  {slug}")
    if not (sparse or thin or no_embed):
        print("all topics clear strong floor with >=3 strong chunks.")


# ---- grep -----------------------------------------------------------------

def cmd_grep(course_slug: str, keyword: str, limit: int, full: bool) -> None:
    conn = db.get_conn()
    preview_len = 4000 if full else 200
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c."sourcePath", c."pageNumber", c."chunkIndex",
                   substring(c.content, 1, %s), length(c.content)
            FROM "Chunk" c
            JOIN "Course" co ON co.id = c."courseId"
            WHERE co.slug = %s AND c.content ILIKE %s
            ORDER BY c."sourcePath", c."chunkIndex"
            LIMIT %s
            """,
            (preview_len, course_slug, f"%{keyword}%", limit),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"no chunks in course={course_slug!r} match {keyword!r}")
        return

    print(f"{len(rows)} chunk(s) match {keyword!r} in {course_slug!r}:\n")
    for cid, sp, pg, ci, preview, total_len in rows:
        page = f" p.{pg}" if pg is not None else ""
        suffix = "" if full or total_len <= preview_len else f"  ... [{total_len} chars total]"
        print(f"  {sp}{page} idx={ci} id={cid}")
        print(f"    {preview!r}{suffix}\n")


# ---- show -----------------------------------------------------------------

def cmd_show(chunk_id: str) -> None:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT "sourcePath", "pageNumber", "chunkIndex", "sectionPath",
                   "tokenCount", content
            FROM "Chunk"
            WHERE id = %s
            """,
            (chunk_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"no chunk with id={chunk_id!r}")
    sp, pg, ci, sec, toks, content = row
    page = f" p.{pg}" if pg is not None else ""
    print(f"chunk {chunk_id}")
    print(f"  source:   {sp}{page} idx={ci}")
    if sec:
        print(f"  section:  {sec}")
    if toks is not None:
        print(f"  tokens:   {toks}")
    print(f"  chars:    {len(content)}")
    print("  --- content ---")
    print(content)


# ---- CLI ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_survey = sub.add_parser("survey", help="per-topic similarity distribution")
    p_survey.add_argument("--course", required=True)
    p_survey.add_argument("--k", type=int, default=8)
    p_survey.add_argument("--strong-floor", type=float, default=0.75,
                          help="similarity at or above which a chunk is 'strong' (default 0.75)")
    p_survey.add_argument("--weak-floor", type=float, default=0.70,
                          help="top similarity below this flags a topic SPARSE (default 0.70)")

    p_grep = sub.add_parser("grep", help="find chunks containing a keyword")
    p_grep.add_argument("--course", required=True)
    p_grep.add_argument("--keyword", required=True)
    p_grep.add_argument("--limit", type=int, default=20)
    p_grep.add_argument("--full", action="store_true",
                        help="print full chunk content instead of 200-char preview")

    p_show = sub.add_parser("show", help="dump one chunk by id")
    p_show.add_argument("chunk_id")

    args = parser.parse_args()
    try:
        if args.cmd == "survey":
            cmd_survey(args.course, args.k, args.strong_floor, args.weak_floor)
        elif args.cmd == "grep":
            cmd_grep(args.course, args.keyword, args.limit, args.full)
        elif args.cmd == "show":
            cmd_show(args.chunk_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()