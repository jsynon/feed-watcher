import contextlib
import csv
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

    def test_relevance_score_rewards_topics_thinkers_and_sadler_modestly(self):
        generic = {"title": "A new essay", "source": "Independent Journal"}
        philosophical = {"title": "Kant on moral philosophy and justice", "source": "Independent Journal"}
        sadler = {"title": "A new essay", "source": "Gregory B. Sadler - That Philosophy Guy"}
        generic_score, _ = watcher.relevance_score(generic)
        philosophy_score, reasons = watcher.relevance_score(philosophical)
        sadler_score, sadler_reasons = watcher.relevance_score(sadler)
        self.assertGreater(philosophy_score, generic_score)
        self.assertIn("thinkers: Kant", "; ".join(reasons))
        self.assertEqual(sadler_score, generic_score + 2)
        self.assertTrue(any("Gregory Sadler" in reason for reason in sadler_reasons))

    def test_science_articles_qualify_and_quanta_gets_a_modest_source_bonus(self):
        quanta = {
            "title": "A new result in quantum physics",
            "source": "Quanta Magazine",
            "published_at": "2026-10-17T10:00:00+00:00",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        general_science = {
            "title": "A new result in quantum physics",
            "source": "Science Journal",
            "published_at": "2026-10-17T10:00:00+00:00",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        self.assertEqual(watcher.rank_candidates([quanta], {})[0], quanta)
        quanta_score, reasons = watcher.relevance_score(quanta)
        other_score, _ = watcher.relevance_score(general_science)
        self.assertEqual(quanta_score, other_score + 2)
        self.assertTrue(any("science topics" in reason for reason in reasons))


    def test_quanta_cell_microscopy_article_is_eligible(self):
        article = {
            "title": "See Inside Cells Like Never Before in These Vivid Microscopic Images",
            "source": "Quanta Magazine",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        self.assertEqual(watcher.rank_candidates([article], {}), [article])
        _, reasons = watcher.relevance_score(article)
        self.assertTrue(any("science topics: cells" in reason for reason in reasons))
        self.assertTrue(any("microscopic" in reason for reason in reasons))


    def test_literature_and_culture_articles_are_eligible(self):
        literature = {
            "title": "Reading Dostoevsky through the modern novel",
            "source": "Literary Review", "targets": {"facebook": "pending", "x": "pending"},
        }
        culture = {
            "title": "How popular culture reshapes our view of myth",
            "source": "Culture Journal", "targets": {"facebook": "pending", "x": "pending"},
        }
        self.assertIn(literature, watcher.rank_candidates([literature], {}))
        self.assertIn(culture, watcher.rank_candidates([culture], {}))

    def test_expanded_vocabulary_catches_common_subject_word_forms(self):
        item = {
            "title": "Ethical questions about mathematical discovery and artistic tradition",
            "source": "Interdisciplinary Review",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        ranked = watcher.rank_candidates([item], {})
        self.assertEqual(ranked, [item])
        _, reasons = watcher.relevance_score(item)
        combined = "; ".join(reasons)
        self.assertIn("ethical", combined)
        self.assertIn("mathematical", combined)
        self.assertIn("artistic", combined)

    def test_personal_cat_shelter_post_is_rejected_even_from_sadler(self):
        personal = {
            "title": "My day at the local cat shelter",
            "summary": "Gregory Sadler talks about philosophy while visiting cats.",
            "author": "Gregory B. Sadler",
            "source": "Gregory B. Sadler - That Philosophy Guy",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        self.assertTrue(watcher.is_personal_content(personal))
        self.assertEqual(watcher.rank_candidates([personal], {}), [])

    def test_sadler_is_deprioritized_when_recently_posted_and_alternatives_exist(self):
        sadler = {"title": "Aristotle on virtue ethics", "source": "Gregory Sadler Substack",
                  "published_at": "2026-10-17T10:00:00+00:00", "targets": {"facebook": "pending", "x": "pending"}}
        other = {"title": "A note on metaphysics", "source": "Another Journal",
                 "published_at": "2026-10-17T09:00:00+00:00", "targets": {"facebook": "pending", "x": "pending"}}
        ranked = watcher.rank_candidates([sadler, other], {"recent_posted_sources": ["gregory-sadler"]})
        self.assertIs(ranked[0], other)
        # Without a recent Sadler post, his topic score plus source bonus wins.
        ranked = watcher.rank_candidates([sadler, other], {})
        self.assertIs(ranked[0], sadler)

    def test_source_bonus_does_not_make_unrelated_article_eligible(self):
        unrelated = {
            "title": "A new article about local gardening",
            "source": "Gregory B. Sadler - That Philosophy Guy",
            "published_at": "2026-10-17T10:00:00+00:00",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        self.assertEqual(watcher.rank_candidates([unrelated], {}), [])

    def test_preview_holds_unrelated_article_without_publishing(self):
        item = {
            "title": "A new guide to summer gadgets",
            "source": "Nautilus", "url": "https://example.com/health",
            "published_at": watcher.iso(),
            "targets": {"facebook": "pending", "x": "pending"},
        }
        state = {"queue": [item]}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            watcher.try_publish(state, {"publishing_enabled": False}, dry_run=True)
        self.assertIn("No queued article passed the subject and personal-content filters", output.getvalue())
        self.assertEqual(state["queue"], [item])

    def test_generic_health_match_alone_does_not_qualify_supplementary_article(self):
        item = {
            "title": "Teen Girls Are Now More Likely to Vape Than Boys",
            "summary": "Smokers gained a way to get nicotine without negative health effects.",
            "categories": ["Health"], "source": "Nautilus",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        self.assertFalse(watcher.has_subject_relevance(item))
        self.assertEqual(watcher.rank_candidates([item], {}), [])

    def test_two_distinct_supplementary_content_signals_qualify(self):
        item = {
            "title": "A new finding",
            "summary": "Researchers report a mathematical result in a study.",
            "categories": ["Science"], "source": "Quanta Magazine",
            "targets": {"facebook": "pending", "x": "pending"},
        }
        self.assertTrue(watcher.has_subject_relevance(item))
        self.assertEqual(watcher.rank_candidates([item], {}), [item])

    def test_poll_queues_only_dated_items_newer_than_baseline(self):
        local_now = dt.datetime.now().astimezone()
        now = dt.datetime.combine(local_now.date(), dt.time(12, 0), tzinfo=local_now.tzinfo).astimezone(dt.timezone.utc)
        feed = {"title": "Test philosophy feed", "url": "https://example.com/feed"}
        fresh_url = "https://example.com/fresh"
        old_url = "https://example.com/old"
        undated_url = "https://example.com/undated"
        yesterday_url = "https://example.com/yesterday"
        yesterday = dt.datetime.combine(
            local_now.date() - dt.timedelta(days=1), dt.time(23, 59), tzinfo=local_now.tzinfo
        )
        items = [
            {"title": "New essay", "url": fresh_url, "published_at": (now - dt.timedelta(minutes=5)).isoformat(), "key": watcher.article_key(fresh_url)},
            {"title": "Old essay", "url": old_url, "published_at": (now - dt.timedelta(days=2)).isoformat(), "key": watcher.article_key(old_url)},
            {"title": "No timestamp", "url": undated_url, "published_at": None, "key": watcher.article_key(undated_url)},
            {"title": "Yesterday's essay", "url": yesterday_url, "published_at": yesterday.isoformat(), "key": watcher.article_key(yesterday_url)},
        ]
        state = {"baseline_at": (now - dt.timedelta(days=30)).isoformat(), "last_checked": {}, "seen": {}, "queue": [], "feed_errors": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "rejected_articles.csv"
            with patch.object(watcher, "REJECTIONS_PATH", report), patch.object(watcher, "feedparser", object()), patch.object(watcher, "fetch_many", return_value=[(feed, items, None)]):
                count = watcher.poll_feeds(state, [feed], {"poll_interval_minutes": 60, "max_age_days_for_new_items": 30})
        self.assertEqual(count, 1)
        self.assertEqual([row["url"] for row in state["queue"]], [fresh_url])
        self.assertIn(watcher.article_key(old_url), state["seen"])
        self.assertIn(watcher.article_key(undated_url), state["seen"])
        self.assertIn(watcher.article_key(yesterday_url), state["seen"])


    def test_poll_records_rejected_article_details_and_deduplicates_report(self):
        local_now = dt.datetime.now().astimezone()
        now = dt.datetime.combine(local_now.date(), dt.time(12, 0), tzinfo=local_now.tzinfo).astimezone(dt.timezone.utc)
        feed = {"title": "Test philosophy feed", "url": "https://example.com/feed"}
        unrelated_url = "https://example.com/unrelated"
        yesterday_url = "https://example.com/yesterday"
        yesterday = dt.datetime.combine(
            local_now.date() - dt.timedelta(days=1), dt.time(12, 0), tzinfo=local_now.tzinfo
        ).astimezone(dt.timezone.utc)
        items = [
            {
                "title": "A new guide to summer gadgets", "summary": "A product roundup.",
                "author": "A. Writer", "url": unrelated_url,
                "published_at": (now - dt.timedelta(minutes=5)).isoformat(),
                "key": watcher.article_key(unrelated_url),
            },
            {
                "title": "A new essay on Kant", "url": yesterday_url,
                "published_at": yesterday.isoformat(),
                "key": watcher.article_key(yesterday_url),
            },
        ]
        state = {
            "baseline_at": (now - dt.timedelta(days=30)).isoformat(),
            "last_checked": {}, "seen": {}, "queue": [], "feed_errors": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "rejected_articles.csv"
            with patch.object(watcher, "REJECTIONS_PATH", report), patch.object(watcher, "feedparser", object()), patch.object(watcher, "fetch_many", return_value=[(feed, items, None)]):
                watcher.poll_feeds(state, [feed], {"poll_interval_minutes": 60})
                watcher.poll_feeds(state, [feed], {"poll_interval_minutes": 60}, force=True)
            with report.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 2)
        unrelated = next(row for row in rows if row["url"] == unrelated_url)
        self.assertEqual(unrelated["source"], feed["title"])
        self.assertEqual(unrelated["title"], "A new guide to summer gadgets")
        self.assertEqual(unrelated["author"], "A. Writer")
        self.assertIn("Subject-relevance filter", unrelated["rejection_reason"])
        older = next(row for row in rows if row["url"] == yesterday_url)
        self.assertIn("Publication-date filter", older["rejection_reason"])
        self.assertIn("Kant", older["matched_topics"])
        self.assertEqual(state["seen"][watcher.article_key(yesterday_url)]["skip_reason"].split(":")[0],
                         "Publication-date filter")

    def test_publish_disabled_never_calls_buffer(self):
        item = {"title": "A philosophy test article", "url": "https://example.com/test", "source": "Test",
                "published_at": watcher.iso(),
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

    def test_post_text_includes_author_and_source_when_available(self):
        item = {"title": "Essay title", "author": "Jane Writer", "source": "A Philosophy Journal",
                "url": "https://example.com/essay"}
        self.assertEqual(watcher.build_post_text(item),
                         "Essay title\nBy: Jane Writer\nSource: A Philosophy Journal\nhttps://example.com/essay")
        self.assertEqual(watcher.build_facebook_text(item),
                         "Essay title\nBy: Jane Writer\nSource: A Philosophy Journal")

    def test_missing_author_is_omitted_without_dangling_separator(self):
        item = {"title": "Essay title", "source": "A Philosophy Journal",
                "url": "https://example.com/essay"}
        self.assertEqual(watcher.build_post_text(item),
                         "Essay title\nSource: A Philosophy Journal\nhttps://example.com/essay")
        self.assertEqual(watcher.build_facebook_text(item),
                         "Essay title\nSource: A Philosophy Journal")

    def test_entry_author_uses_feed_author_fields(self):
        self.assertEqual(watcher.entry_author({"authors": [{"name": "  Jane   Writer "}]}), "Jane Writer")
        self.assertEqual(watcher.entry_author({}), "")

    def test_facebook_posts_include_regular_post_type(self):
        response = {"data": {"createPost": {"post": {"id": "post-1", "status": "sent"}}}}
        with patch.object(watcher, "buffer_request", return_value=response) as request:
            metadata = {"type": "post", "linkAttachment": {
                "url": "https://example.com", "title": "Title",
                "thumbnail": {"url": "https://example.com/image.jpg"},
            }}
            ok, _ = watcher.create_post("key", "facebook-channel", "Title", "facebook", metadata)
        self.assertTrue(ok)
        self.assertEqual(request.call_args.args[2]["input"]["metadata"], {"facebook": metadata})

    def test_facebook_card_reads_open_graph_image_and_description(self):
        class Response(io.BytesIO):
            headers = type("Headers", (), {"get_content_charset": lambda self: "utf-8"})()
        page = b'<meta property="og:title" content="Page title"><meta property="og:description" content="A useful description"><meta property="og:image" content="/cover.jpg">'
        item = {"title": "Feed title", "url": "https://example.com/article"}
        with patch.object(watcher.urllib.request, "urlopen", return_value=Response(page)):
            result = watcher.facebook_link_attachment(item)
        self.assertEqual(result["title"], "Page title")
        self.assertEqual(result["description"], "A useful description")
        self.assertEqual(result["thumbnail"], {"url": "https://example.com/cover.jpg"})

    def test_facebook_retry_does_not_resend_already_sent_x_post(self):
        now = dt.datetime.now(dt.timezone.utc)
        old = (now - dt.timedelta(hours=3)).isoformat()
        item = {
            "title": "Test article", "url": "https://example.com/test", "source": "Test",
            "published_at": now.isoformat(),
            "targets": {"facebook": "retry", "x": "sent"},
            "attempts": {"facebook": 1, "x": 1}, "errors": {
                "facebook": "previous rejection", "facebook_at": old,
            }, "counted_day": now.date().isoformat(),
        }
        state = {"queue": [item], "sent_today": {now.date().isoformat(): 1},
                 "last_article_posted_at": old}
        with patch.object(watcher, "load_dotenv", return_value={"BUFFER_API_KEY": "test-key"}), \
             patch.object(watcher, "create_post", return_value=(True, "accepted")) as create, \
             patch.object(watcher, "facebook_link_attachment", return_value={
                 "url": "https://example.com/test", "title": "Test article",
             }), \
             patch.object(watcher, "save_json"):
            watcher.try_publish(state, {
                "publishing_enabled": True, "facebook_channel_id": "fb-id", "x_channel_id": "x-id",
                "minimum_hours_between_articles": 2, "retry_wait_minutes": 60,
            })
        create.assert_called_once_with(
            "test-key", "fb-id", "Test article\nSource: Test", "facebook",
            {"type": "post", "linkAttachment": {"url": "https://example.com/test", "title": "Test article"}},
        )
        self.assertEqual(item["targets"]["x"], "sent")
        self.assertEqual(item["targets"]["facebook"], "sent")
        self.assertEqual(state["queue"], [])

    def test_partial_crosspost_can_finish_despite_article_pacing_limits(self):
        now = dt.datetime.now(dt.timezone.utc)
        old = (now - dt.timedelta(hours=3)).isoformat()
        recent = (now - dt.timedelta(minutes=5)).isoformat()

        # A reached daily cap and a recent article are each allowed to block
        # new articles, but neither should strand an article already sent to X.
        cases = [
            ("daily cap", 1, old),
            ("minimum gap", 0, recent),
        ]
        for label, sent_count, last_post in cases:
            with self.subTest(label=label):
                item = {
                    "title": "Test article", "url": "https://example.com/test", "source": "Test",
                    "published_at": now.isoformat(),
                    "targets": {"facebook": "retry", "x": "sent"},
                    "attempts": {"facebook": 1, "x": 1}, "errors": {
                        "facebook": "previous rejection", "facebook_at": old,
                    }, "counted_day": now.date().isoformat(),
                }
                state = {"queue": [item], "sent_today": {now.date().isoformat(): sent_count},
                         "last_article_posted_at": last_post}
                with patch.object(watcher, "load_dotenv", return_value={"BUFFER_API_KEY": "test-key"}), \
                     patch.object(watcher, "create_post", return_value=(True, "accepted")) as create, \
                     patch.object(watcher, "facebook_link_attachment", return_value={
                         "url": "https://example.com/test", "title": "Test article",
                     }), \
                     patch.object(watcher, "save_json"):
                    watcher.try_publish(state, {
                        "publishing_enabled": True, "facebook_channel_id": "fb-id", "x_channel_id": "x-id",
                        "minimum_hours_between_articles": 2, "max_articles_per_day": 1,
                        "retry_wait_minutes": 60,
                    })

                create.assert_called_once()
                self.assertEqual(create.call_args.args[3], "facebook")
                self.assertEqual(item["targets"]["x"], "sent")
                self.assertEqual(item["targets"]["facebook"], "sent")
                self.assertEqual(state["queue"], [])

    def test_publish_discards_previous_day_queue_items(self):
        now = dt.datetime.now().astimezone()
        yesterday = now - dt.timedelta(days=1)
        item = {
            "title": "Yesterday's article", "url": "https://example.com/yesterday", "source": "Test",
            "published_at": yesterday.isoformat(),
            "targets": {"facebook": "pending", "x": "pending"},
            "attempts": {"facebook": 0, "x": 0},
        }
        state = {"queue": [item]}
        output = io.StringIO()
        with patch.object(watcher, "create_post", side_effect=AssertionError("must not publish")), \
             contextlib.redirect_stdout(output):
            result = watcher.try_publish(state, {"publishing_enabled": False})
        self.assertFalse(result)
        self.assertEqual(state["queue"], [])
        self.assertIn("Discarded 1 queued article", output.getvalue())


if __name__ == "__main__":
    unittest.main()
