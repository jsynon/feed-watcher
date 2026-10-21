import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

import semantic_sample


def entry(title, url, published_at):
    return {
        "title": title,
        "url": url,
        "published_at": published_at,
        "summary": f"Summary for {title}",
        "categories": ["philosophy", "culture"],
    }


class SemanticSampleTests(unittest.TestCase):
    def setUp(self):
        self.newest = "2026-10-21T12:00:00+00:00"
        self.older = "2026-10-20T12:00:00+00:00"

    def test_sample_is_source_balanced_and_newest_first(self):
        results = [
            ({"title": "Source A", "url": "https://a.example/feed"}, [
                entry("A old", "https://a.example/old", self.older),
                entry("A new", "https://a.example/new", self.newest),
            ], None),
            ({"title": "Source B", "url": "https://b.example/feed"}, [
                entry("B old", "https://b.example/old", self.older),
                entry("B new", "https://b.example/new", self.newest),
            ], None),
            ({"title": "Source C", "url": "https://c.example/feed"}, [
                entry("C old", "https://c.example/old", self.older),
                entry("C new", "https://c.example/new", self.newest),
            ], None),
        ]

        rows = semantic_sample.select_sample(results, sample_size=5, per_feed=2)

        self.assertEqual(len(rows), 5)
        counts = {}
        for row in rows:
            counts[row["source"]] = counts.get(row["source"], 0) + 1
        self.assertLessEqual(max(counts.values()), 2)
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        for source in counts:
            source_rows = [row for row in rows if row["source"] == source]
            if len(source_rows) == 2:
                self.assertTrue(source_rows[0]["title"].endswith("new"))

    def test_sample_deduplicates_canonical_urls(self):
        results = [
            ({"title": "First", "url": "https://first.example/feed"}, [
                entry("Shared article", "https://example.org/story?utm_source=feed", self.newest),
            ], None),
            ({"title": "Second", "url": "https://second.example/feed"}, [
                entry("Shared article", "https://example.org/story", self.newest),
            ], None),
        ]

        rows = semantic_sample.select_sample(results, sample_size=10, per_feed=2)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://example.org/story")

    def test_csv_has_empty_review_fields_and_excel_friendly_encoding(self):
        rows = semantic_sample.select_sample([
            ({"title": "Source", "url": "https://source.example/feed"}, [
                entry("An article", "https://example.org/story", self.newest),
            ], None),
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.csv"
            semantic_sample.write_sample_csv(rows, path)
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                parsed = list(csv.DictReader(handle))
        self.assertEqual(parsed[0]["reviewer_label"], "")
        self.assertEqual(parsed[0]["reviewer_notes"], "")
        self.assertEqual(parsed[0]["categories"], "philosophy; culture")

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            semantic_sample.select_sample([], sample_size=0)
        with self.assertRaises(ValueError):
            semantic_sample.select_sample([], per_feed=0)


if __name__ == "__main__":
    unittest.main()
