import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import watcher


class WatcherTests(unittest.TestCase):
    def test_opml_contains_only_the_84_feeds_folder_sources(self):
        feeds = watcher.load_feeds()
        self.assertEqual(len(feeds), 84)
        self.assertTrue(all(feed["url"].startswith(("http://", "https://")) for feed in feeds))

    def test_tracking_parameters_do_not_create_duplicate_articles(self):
        first = "https://example.com/article?utm_source=feedly&id=7#section"
        second = "https://EXAMPLE.com/article?id=7"
        self.assertEqual(watcher.canonical_url(first), watcher.canonical_url(second))
        self.assertEqual(watcher.article_key(first), watcher.article_key(second))

    def test_poll_queues_only_dated_items_newer_than_baseline(self):
        now = dt.datetime.now(dt.timezone.utc)
        feed = {"title": "Test philosophy feed", "url": "https://example.com/feed"}
        fresh_url = "https://example.com/fresh"
        old_url = "https://example.com/old"
        undated_url = "https://example.com/undated"
        items = [
            {"title": "New essay", "url": fresh_url, "published_at": (now - dt.timedelta(minutes=5)).isoformat(), "key": watcher.article_key(fresh_url)},
            {"title": "Old essay", "url": old_url, "published_at": (now - dt.timedelta(days=2)).isoformat(), "key": watcher.article_key(old_url)},
            {"title": "No timestamp", "url": undated_url, "published_at": None, "key": watcher.article_key(undated_url)},
        ]
        state = {"baseline_at": (now - dt.timedelta(days=1)).isoformat(), "last_checked": {}, "seen": {}, "queue": [], "feed_errors": {}}
        with patch.object(watcher, "feedparser", object()), patch.object(watcher, "fetch_many", return_value=[(feed, items, None)]):
            count = watcher.poll_feeds(state, [feed], {"poll_interval_minutes": 60, "max_age_days_for_new_items": 30})
        self.assertEqual(count, 1)
        self.assertEqual([row["url"] for row in state["queue"]], [fresh_url])
        self.assertIn(watcher.article_key(old_url), state["seen"])
        self.assertIn(watcher.article_key(undated_url), state["seen"])

    def test_publish_disabled_never_calls_buffer(self):
        item = {"title": "Test article", "url": "https://example.com/test", "source": "Test",
                "targets": {"facebook": "pending", "x": "pending"}, "attempts": {"facebook": 0, "x": 0}}
        state = {"queue": [item]}
        output = io.StringIO()
        with patch.object(watcher, "create_post", side_effect=AssertionError("must not publish")), contextlib.redirect_stdout(output):
            result = watcher.try_publish(state, {"publishing_enabled": False})
        self.assertFalse(result)
        self.assertEqual(item["targets"]["facebook"], "pending")
        self.assertIn("PUBLISHING IS OFF", output.getvalue())

    def test_preview_reports_empty_queue_and_recent_baseline_poll(self):
        state = {"baseline_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "last_checked": {"https://example.com/feed": dt.datetime.now(dt.timezone.utc).isoformat()},
                 "seen": {}, "queue": [], "feed_errors": {}}
        with patch.object(watcher, "feedparser", object()):
            watcher.poll_feeds(state, [{"title": "Test", "url": "https://example.com/feed"}], {"poll_interval_minutes": 60})
        self.assertEqual(state["last_check_result"], "not_due")
        self.assertEqual(state["last_check_feed_count"], 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            watcher.try_publish(state, {"publishing_enabled": False}, dry_run=True)
        self.assertIn("Queue is empty; nothing to preview", output.getvalue())

    def test_x_post_keeps_url_and_fits_conservative_length_when_possible(self):
        item = {"title": "A" * 400, "url": "https://example.com/article"}
        text = watcher.build_post_text(item)
        self.assertTrue(text.endswith(item["url"]))
        self.assertLessEqual(len(text), 275)


if __name__ == "__main__":
    unittest.main()
