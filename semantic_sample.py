#!/usr/bin/env python3
"""Export a source-balanced, read-only sample of recent RSS entries for review."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import random
import sys
from pathlib import Path

import watcher


SAMPLE_FIELDS = (
    "source",
    "title",
    "author",
    "published_at",
    "categories",
    "summary",
    "url",
    "reviewer_label",
    "reviewer_notes",
)
DEFAULT_SAMPLE_SIZE = 60
DEFAULT_PER_FEED = 2
REVIEW_LABELS = ("relevant", "not relevant", "uncertain")


def _publication_sort_key(item: dict) -> dt.datetime:
    parsed = watcher.parse_datetime(item.get("published_at"))
    return parsed or dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def select_sample(
    feed_results: list[tuple[dict, list[dict], str | None]],
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    per_feed: int = DEFAULT_PER_FEED,
) -> list[dict]:
    """Choose newest unique items round-robin, with a per-feed ceiling."""
    if sample_size < 1:
        raise ValueError("sample_size must be at least 1")
    if per_feed < 1:
        raise ValueError("per_feed must be at least 1")

    grouped: list[tuple[str, list[dict]]] = []
    seen_urls: set[str] = set()

    for feed, items, _error in sorted(
        feed_results, key=lambda row: row[0].get("title", "").casefold()
    ):
        source = str(feed.get("title") or feed.get("url") or "Unknown source")
        candidates = []
        for item in items:
            url = watcher.canonical_url(str(item.get("url") or ""))
            title = str(item.get("title") or "").strip()
            if not url or not title or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append({
                "source": source,
                "title": title,
                "author": str(item.get("author") or "").strip(),
                "published_at": str(item.get("published_at") or "").strip(),
                "categories": "; ".join(
                    str(category).strip()
                    for category in item.get("categories", [])
                    if str(category).strip()
                ),
                "summary": str(item.get("summary") or "").strip(),
                "url": url,
                "reviewer_label": "",
                "reviewer_notes": "",
            })
        candidates.sort(key=_publication_sort_key, reverse=True)
        if candidates:
            grouped.append((source, candidates))

    # Mix the source order before round-robin selection so OPML ordering does not
    # determine which feeds appear first when the requested sample is small.
    random.Random(2026).shuffle(grouped)

    selected = []
    depth = 0
    while len(selected) < sample_size:
        added_at_this_depth = False
        for _source, candidates in grouped:
            if depth < min(len(candidates), per_feed):
                selected.append(candidates[depth])
                added_at_this_depth = True
                if len(selected) >= sample_size:
                    break
        if not added_at_this_depth:
            break
        depth += 1
    return selected


def write_sample_csv(rows: list[dict], path: Path) -> None:
    """Write an Excel-friendly UTF-8 CSV with empty editorial review columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def default_output_path(now: dt.datetime | None = None) -> Path:
    stamp = (now or dt.datetime.now().astimezone()).strftime("%Y%m%d_%H%M%S")
    candidate = watcher.ROOT / f"semantic_review_sample_{stamp}.csv"
    suffix = 2
    while candidate.exists():
        candidate = watcher.ROOT / f"semantic_review_sample_{stamp}_{suffix}.csv"
        suffix += 1
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a source-balanced RSS sample for manual relevance review; never publishes."
    )
    parser.add_argument(
        "--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE,
        help=f"maximum number of entries to export (default: {DEFAULT_SAMPLE_SIZE})",
    )
    parser.add_argument(
        "--per-feed", type=int, default=DEFAULT_PER_FEED,
        help=f"maximum entries from each source (default: {DEFAULT_PER_FEED})",
    )
    parser.add_argument(
        "--output", type=Path,
        help="CSV destination (default: a new timestamped file in the watcher folder)",
    )
    args = parser.parse_args(argv)

    if args.sample_size < 1 or args.per_feed < 1:
        parser.error("--sample-size and --per-feed must both be at least 1")
    if watcher.feedparser is None:
        print("ERROR: feedparser is not installed. Run setup.bat first.", file=sys.stderr)
        return 1

    feeds = watcher.load_feeds()
    print(f"Fetching RSS entries from {len(feeds)} feeds. This is read-only; no posts will be sent.")
    results = watcher.fetch_many(feeds)
    errors = sum(bool(error) for _feed, _items, error in results)
    rows = select_sample(results, args.sample_size, args.per_feed)
    if not rows:
        print("No usable article entries were found; no CSV was written.", file=sys.stderr)
        print(f"Feed errors: {errors} of {len(results)}")
        return 1

    output = args.output or default_output_path()
    if not output.is_absolute():
        output = watcher.ROOT / output
    write_sample_csv(rows, output)
    successful = len(results) - errors
    print(f"Exported {len(rows)} article(s) from {successful} feed(s); {errors} feed(s) reported errors.")
    print(f"Review file: {output}")
    print("Fill reviewer_label with: relevant, not relevant, or uncertain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
