#!/usr/bin/env python3
"""Poll a Feedly OPML folder and pace new articles through Buffer."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from html.parser import HTMLParser

try:
    import feedparser
except ImportError:
    feedparser = None

ROOT = Path(__file__).resolve().parent
OPML_PATH = ROOT / "feeds.opml"
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
ENV_PATH = ROOT / ".env"
LOG_PATH = ROOT / "watcher.log"
BUFFER_API = "https://api.buffer.com"
USER_AGENT = "AntilogicalismFeedWatcher/1.0 (+local personal automation)"
MAX_FEED_BYTES = 8 * 1024 * 1024


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime | None = None) -> str:
    return (value or utcnow()).isoformat(timespec="seconds")


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (ValueError, TypeError):
        return None


def local_publication_date(value: str | None) -> dt.date | None:
    """Return an article's publication date in the computer's local timezone."""
    parsed = parse_datetime(value)
    return parsed.astimezone().date() if parsed else None


def canonical_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {
                 "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"
             }]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                                   urllib.parse.urlencode(query, doseq=True), ""))


def article_key(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_config() -> dict:
    defaults = {
        "publishing_enabled": False,
        "facebook_channel_id": "",
        "x_channel_id": "",
        "poll_interval_minutes": 60,
        "minimum_hours_between_articles": 1,
        "max_articles_per_day": 10,
        "max_auto_retries": 3,
        "retry_wait_minutes": 60
    }
    current = load_json(CONFIG_PATH, {})
    defaults.update(current)
    return defaults


def load_dotenv() -> dict[str, str]:
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_feeds() -> list[dict]:
    if not OPML_PATH.exists():
        raise RuntimeError("feeds.opml is missing from the watcher folder.")
    root = ET.parse(OPML_PATH).getroot()
    body = root.find("body")
    if body is None:
        raise RuntimeError("The OPML file has no body section.")
    folder = next((item for item in body.findall("outline")
                   if (item.get("text") or item.get("title") or "").strip().casefold() == "feeds"), None)
    if folder is None:
        raise RuntimeError("Could not find the 'Feeds' folder in feeds.opml.")
    feeds = []
    for item in folder.iter("outline"):
        url = item.get("xmlUrl") or item.get("xmlurl")
        if url:
            feeds.append({"title": item.get("title") or item.get("text") or url, "url": url})
    return feeds


def fetch_and_parse(feed: dict) -> tuple[dict, list[dict], str | None]:
    request = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT,
                                                             "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(MAX_FEED_BYTES + 1)
        if len(raw) > MAX_FEED_BYTES:
            return feed, [], f"feed exceeds {MAX_FEED_BYTES // (1024 * 1024)} MB limit"
        if not feedparser:
            return feed, [], "feedparser is not installed; run setup.bat"
        parsed = feedparser.parse(raw)
        if parsed.bozo and not parsed.entries:
            return feed, [], str(parsed.bozo_exception)[:240]
        items = []
        for entry in parsed.entries:
            url = canonical_url(entry.get("link", ""))
            title = re.sub(r"\s+", " ", str(entry.get("title", "")).strip())
            if not url or not title:
                continue
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_at = None
            if published:
                published_at = dt.datetime(*published[:6], tzinfo=dt.timezone.utc).isoformat(timespec="seconds")
            author = entry_author(entry)
            item = {"title": title, "url": url, "published_at": published_at,
                    "key": article_key(url)}
            if author:
                item["author"] = author
            items.append(item)
        return feed, items, None if items or parsed.feed else "response was not recognized as a feed"
    except urllib.error.HTTPError as exc:
        return feed, [], f"HTTP {exc.code} {exc.reason}"
    except Exception as exc:
        return feed, [], f"{type(exc).__name__}: {exc}"[:240]


def fetch_many(feeds: list[dict]) -> list[tuple[dict, list[dict], str | None]]:
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_and_parse, feed) for feed in feeds]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(({"title": "Unknown feed", "url": ""}, [], str(exc)))
    results.sort(key=lambda row: row[0]["title"].casefold())
    return results


def entry_author(entry) -> str:
    """Return an author when the RSS/Atom entry exposes one."""
    author = entry.get("author") or entry.get("dc_creator") or entry.get("creator")
    if not author:
        authors = entry.get("authors") or []
        if authors:
            first = authors[0]
            author = first.get("name") if hasattr(first, "get") else str(first)
    if isinstance(author, dict):
        author = author.get("name") or author.get("email") or ""
    author = html.unescape(re.sub(r"<[^>]*>", " ", str(author or "")))
    return re.sub(r"\s+", " ", author).strip()


def do_baseline() -> int:
    if STATE_PATH.exists():
        raise RuntimeError("state.json already exists. Baseline is a one-time setup; refusing to overwrite your queue or history.")
    if feedparser is None:
        raise RuntimeError("feedparser is not installed; run setup.bat first.")
    feeds = load_feeds()
    print(f"Taking a no-post baseline from {len(feeds)} feeds…")
    state = {"version": 1, "baseline_at": iso(), "last_polled_at": None,
             "last_article_posted_at": None, "sent_today": {}, "last_checked": {},
             "seen": {}, "queue": [], "feed_errors": {}}
    errors = 0
    for feed, items, error in fetch_many(feeds):
        if error:
            state["feed_errors"][feed["url"]] = {"title": feed["title"], "error": error, "at": iso()}
            errors += 1
        state["last_checked"][feed["url"]] = iso()
        for item in items:
            state["seen"][item["key"]] = {"url": item["url"], "seen_at": state["baseline_at"]}
    save_json(STATE_PATH, state)
    print(f"Baseline saved: {len(state['seen'])} existing article links marked seen; {errors} feeds need retry/repair.")
    print("No posts were created. New dated items after this baseline can enter the queue.")
    return 0


def poll_feeds(state: dict, feeds: list[dict], config: dict, force: bool = False) -> int:
    if feedparser is None:
        raise RuntimeError("feedparser is not installed; run setup.bat first.")
    baseline = parse_datetime(state.get("baseline_at"))
    if not baseline:
        raise RuntimeError("No baseline exists yet. Run setup_baseline.bat first.")
    now = utcnow()
    interval = max(5, int(config.get("poll_interval_minutes", 60)))
    due = []
    for feed in feeds:
        last = parse_datetime(state.get("last_checked", {}).get(feed["url"]))
        if force or not last or (now - last).total_seconds() >= interval * 60:
            due.append(feed)
    if not due:
        state["last_check_result"] = "not_due"
        state["last_check_feed_count"] = 0
        state["last_check_error_count"] = 0
        return 0
    results = fetch_many(due)
    new_count = 0
    today = now.astimezone().date()
    for feed, items, error in results:
        url = feed["url"]
        state["last_checked"][url] = iso(now)
        if error:
            state.setdefault("feed_errors", {})[url] = {"title": feed["title"], "error": error, "at": iso(now)}
            continue
        state.setdefault("feed_errors", {}).pop(url, None)
        for item in items:
            key = item["key"]
            if key in state.setdefault("seen", {}):
                continue
            published = parse_datetime(item.get("published_at"))
            # Only publish an article on its local calendar publication date.
            # Undated, pre-baseline, and prior-day items are marked seen and skipped.
            if (not published or published <= baseline or
                    published.astimezone().date() != today):
                state["seen"][key] = {"url": item["url"], "seen_at": iso(now), "skipped": True}
                continue
            state["seen"][key] = {"url": item["url"], "seen_at": iso(now)}
            state.setdefault("queue", []).append({
                "key": key, "title": item["title"], "url": item["url"],
                "source": feed["title"], "published_at": item["published_at"],
                "queued_at": iso(now), "targets": {"facebook": "pending", "x": "pending"},
                "attempts": {"facebook": 0, "x": 0}, "errors": {}
            })
            if item.get("author"):
                state["queue"][-1]["author"] = item["author"]
            new_count += 1
    state["last_check_result"] = "checked"
    state["last_check_feed_count"] = len(due)
    state["last_check_error_count"] = sum(1 for _, _, error in results if error)
    state["last_polled_at"] = iso(now)
    # Older articles go first; stable order breaks ties by discovery time then title.
    state["queue"].sort(key=lambda x: (x.get("published_at") or "", x.get("queued_at") or "", x.get("title", "").casefold()))
    return new_count


def buffer_request(query: str, api_key: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(BUFFER_API, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": USER_AGENT
    })
    with urllib.request.urlopen(request, timeout=40) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("errors"):
        raise RuntimeError("Buffer API: " + "; ".join(str(e.get("message", e)) for e in result["errors"]))
    return result


def show_channels() -> int:
    api_key = load_dotenv().get("BUFFER_API_KEY") or os.environ.get("BUFFER_API_KEY")
    if not api_key:
        raise RuntimeError("Add BUFFER_API_KEY to .env first.")
    result = buffer_request("query { account { organizations { id name } } }", api_key)
    orgs = result.get("data", {}).get("account", {}).get("organizations", [])
    if not orgs:
        print("No Buffer organizations are visible to this API key.")
        return 1
    for org in orgs:
        query = "query($input: ChannelsInput!) { channels(input: $input) { id service type name displayName externalLink isDisconnected isLocked } }"
        data = buffer_request(query, api_key, {"input": {"organizationId": org["id"]}})
        print(f"\n{org.get('name', 'Buffer organization')} ({org['id']})")
        for channel in data.get("data", {}).get("channels", []):
            print("  - {label} | service={service} type={type} | id={id}{flags}".format(
                label=channel.get("displayName") or channel.get("name") or channel.get("descriptor") or "Channel",
                service=channel.get("service"), type=channel.get("type"), id=channel.get("id"),
                flags=(" | DISCONNECTED" if channel.get("isDisconnected") else "") +
                      (" | LOCKED" if channel.get("isLocked") else "")))
    print("\nCopy the Facebook Page ID and X/Twitter channel ID into config.json.")
    return 0


def create_post(api_key: str, channel_id: str, text: str, service: str,
                metadata: dict | None = None) -> tuple[bool, str]:
    mutation = """mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id status text } }
        ... on MutationError { message }
      }
    }"""
    post_input = {
        "channelId": channel_id, "text": text, "assets": [],
        "schedulingType": "automatic", "mode": "shareNow"
    }
    if service == "facebook":
        post_input["metadata"] = {"facebook": metadata or {"type": "post"}}
    result = buffer_request(mutation, api_key, {"input": post_input})
    outcome = result.get("data", {}).get("createPost", {})
    if outcome.get("post", {}).get("id"):
        post = outcome["post"]
        return True, f"Buffer accepted post {post['id']} ({post.get('status', 'status unknown')})"
    return False, str(outcome.get("message") or outcome or "Buffer returned no post ID")


def build_post_text(item: dict) -> str:
    url = item["url"]
    title = re.sub(r"\s+", " ", item["title"]).strip()
    author = re.sub(r"\s+", " ", str(item.get("author") or "")).strip()
    source = re.sub(r"\s+", " ", str(item.get("source") or "")).strip()
    author_line = f"By: {author}" if author else ""
    source_line = f"Source: {source}" if source else ""
    fixed_lines = [line for line in (author_line, source_line, url) if line]
    fixed_length = sum(map(len, fixed_lines)) + max(0, len(fixed_lines))
    room = max(0, 275 - fixed_length)
    if len(title) > room:
        title = title[:max(0, room - 1)].rstrip() + "…" if room > 1 else ""
    lines = [line for line in (title, author_line, source_line, url) if line]
    return "\n".join(lines)


def build_facebook_text(item: dict) -> str:
    title = re.sub(r"\s+", " ", item["title"]).strip()
    author = re.sub(r"\s+", " ", str(item.get("author") or "")).strip()
    source = re.sub(r"\s+", " ", str(item.get("source") or "")).strip()
    author_line = f"By: {author}" if author else ""
    source_line = f"Source: {source}" if source else ""
    return "\n".join(line for line in (title, author_line, source_line) if line)


class _OpenGraphParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "meta":
            return
        data = {str(k).casefold(): str(v).strip() for k, v in attrs if k and v}
        key = (data.get("property") or data.get("name") or "").casefold()
        content = data.get("content", "")
        if key and content and key not in self.values:
            self.values[key] = content


def facebook_link_attachment(item: dict) -> dict:
    """Build a Facebook link card from the article page's Open Graph metadata."""
    cached = item.get("facebook_link_attachment")
    if cached:
        return cached
    url = item["url"]
    attachment = {"url": url, "title": item["title"]}
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; AntilogicalismFeedWatcher/1.0)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        })
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(1024 * 1024)
            charset = response.headers.get_content_charset() or "utf-8"
        parser = _OpenGraphParser()
        parser.feed(raw.decode(charset, errors="replace"))
        data = parser.values
        title = data.get("og:title") or data.get("twitter:title")
        description = data.get("og:description") or data.get("twitter:description")
        thumbnail = (data.get("og:image:secure_url") or data.get("og:image") or
                     data.get("twitter:image:src") or data.get("twitter:image"))
        if title:
            attachment["title"] = html.unescape(title).strip()[:300]
        if description:
            attachment["description"] = re.sub(r"\s+", " ", html.unescape(description)).strip()[:500]
        if thumbnail:
            thumbnail = urllib.parse.urljoin(url, html.unescape(thumbnail).strip())
            if urllib.parse.urlsplit(thumbnail).scheme in {"http", "https"}:
                attachment["thumbnail"] = {"url": thumbnail}
    except Exception:
        # A blocked or incomplete page should not prevent sharing the article link.
        pass
    item["facebook_link_attachment"] = attachment
    return attachment


def try_publish(state: dict, config: dict, dry_run: bool = False) -> bool:
    queue = state.get("queue", [])
    today = dt.datetime.now().astimezone().date()
    original_count = len(queue)
    queue[:] = [entry for entry in queue
                if local_publication_date(entry.get("published_at")) == today]
    expired_count = original_count - len(queue)
    if expired_count:
        print(f"Discarded {expired_count} queued article(s) not published today.")
    item = next((entry for entry in queue if any(v in {"pending", "retry"} for v in entry["targets"].values())), None)
    if item is None:
        print("Queue is empty; nothing to preview." if dry_run else "Queue is empty; nothing to publish.")
        return False
    if dry_run or not config.get("publishing_enabled"):
        print("PUBLISHING IS OFF. Next queued article:")
        print(f"  {item['title']}\n  {item['url']}\n  source: {item['source']}")
        return False
    values = load_dotenv()
    api_key = values.get("BUFFER_API_KEY") or os.environ.get("BUFFER_API_KEY")
    targets = {"facebook": config.get("facebook_channel_id", ""), "x": config.get("x_channel_id", "")}
    if not api_key or not all(targets.values()):
        raise RuntimeError("Publishing is enabled, but the Buffer key or one of the two channel IDs is missing.")
    now = dt.datetime.now().astimezone()
    day = now.date().isoformat()
    sent_today = state.setdefault("sent_today", {})
    sent_today[day] = int(sent_today.get(day, 0))
    article_had_success = any(item["targets"].get(name) == "sent" for name in targets)
    # Pacing limits apply between distinct articles. If one channel already
    # accepted this item, allow the remaining channel(s) to complete it now.
    if not article_had_success:
        if sent_today[day] >= int(config.get("max_articles_per_day", 5)):
            print(f"Daily cap reached ({sent_today[day]} articles). The queue will wait until tomorrow.")
            return False
        last_post = parse_datetime(state.get("last_article_posted_at"))
        gap = max(0, float(config.get("minimum_hours_between_articles", 2)))
        if last_post and (utcnow() - last_post).total_seconds() < gap * 3600:
            print("Waiting for the configured gap between articles.")
            return False
    article_had_new_success = False
    text = build_post_text(item)
    for name, channel_id in targets.items():
        status = item["targets"].get(name, "pending")
        if status == "sent":
            continue
        if status == "uncertain":
            print(f"{name}: previous result is uncertain; skipping automatically to avoid a duplicate.")
            continue
        failed_at = parse_datetime(item.get("errors", {}).get(name + "_at"))
        retry_wait = max(0, int(config.get("retry_wait_minutes", 60)))
        if status == "retry" and failed_at and (utcnow() - failed_at).total_seconds() < retry_wait * 60:
            print(f"{name}: waiting before the next retry.")
            continue
        attempts = int(item["attempts"].get(name, 0))
        if attempts >= int(config.get("max_auto_retries", 3)):
            item["targets"][name] = "needs_attention"
            print(f"{name}: retry limit reached; review this queued article manually.")
            continue
        item["attempts"][name] = attempts + 1
        try:
            post_text = text
            metadata = None
            if name == "facebook":
                attachment = facebook_link_attachment(item)
                metadata = {"type": "post", "linkAttachment": attachment}
                # Let the Facebook card carry the URL instead of printing a bare URL in the post.
                post_text = build_facebook_text(item)
            ok, message = create_post(api_key, channel_id, post_text, name, metadata)
            if ok:
                item["targets"][name] = "sent"
                item.setdefault("errors", {}).pop(name, None)
                article_had_success = True
                article_had_new_success = True
                print(f"{name}: {message}")
            else:
                item["targets"][name] = "retry"
                item.setdefault("errors", {})[name] = message
                item["errors"][name + "_at"] = iso()
                print(f"{name}: Buffer rejected the post: {message}")
        except urllib.error.HTTPError as exc:
            # Buffer's 4xx responses are rejected; retry later except auth/config errors.
            message = f"HTTP {exc.code}: {exc.reason}"
            if exc.code in (401, 403, 400):
                item["targets"][name] = "needs_attention"
            else:
                item["targets"][name] = "retry"
            item.setdefault("errors", {})[name] = message
            item["errors"][name + "_at"] = iso()
            print(f"{name}: {message}")
        except Exception as exc:
            # A lost response can mean Buffer accepted the post; do not risk duplicate retry.
            item["targets"][name] = "uncertain"
            item.setdefault("errors", {})[name] = f"{type(exc).__name__}: {exc}"
            print(f"{name}: result uncertain; not retrying automatically ({exc})")
    if article_had_success:
        if not item.get("counted_day"):
            sent_today[day] += 1
            item["counted_day"] = day
    if article_had_new_success:
        state["last_article_posted_at"] = iso(utcnow())
    # Remove only after both destinations have accepted it.
    if all(item["targets"].get(name) == "sent" for name in targets):
        queue.remove(item)
        print("Cross-post complete; article removed from the queue.")
    else:
        print("Article remains queued until both channels are accounted for.")
    save_json(STATE_PATH, state)
    return article_had_success


def show_status(state: dict) -> int:
    print(f"Baseline: {state.get('baseline_at') or 'not set'}")
    print(f"Last poll: {state.get('last_polled_at') or 'not yet'}")
    print(f"Queued articles: {len(state.get('queue', []))}")
    print(f"Feeds with latest errors: {len(state.get('feed_errors', {}))}")
    for item in state.get("queue", [])[:10]:
        print(f"  [{', '.join(f'{k}:{v}' for k, v in item.get('targets', {}).items())}] {item['title']}")
    if len(state.get("queue", [])) > 10:
        print("  …")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Feedly Feeds folder → paced Buffer posts")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--baseline", action="store_true", help="mark current feed items as seen; never posts")
    group.add_argument("--run-once", action="store_true", help="poll due feeds, queue new items, and process at most one article")
    group.add_argument("--channels", action="store_true", help="list connected Buffer channel IDs; never posts")
    group.add_argument("--status", action="store_true", help="show queue and feed health summary")
    group.add_argument("--dry-run", action="store_true", help="poll and show next queued item without posting")
    group.add_argument("--retry-failures", action="store_true", help="make rejected items eligible for another attempt; never resets uncertain results")
    args = parser.parse_args()
    class Tee:
        # pythonw.exe has no console streams. Keep the file logger working
        # while safely omitting sys.__stdout__/sys.__stderr__ when absent.
        def __init__(self, console_stream, log_stream):
            self.console_stream = console_stream
            self.log_stream = log_stream
            self.pending = ""

        def write(self, value):
            if self.console_stream is not None:
                self.console_stream.write(value)
                self.console_stream.flush()
            self.pending += value
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
                self.log_stream.write(f"[{stamp}] {line}\n")
                self.log_stream.flush()

        def flush(self):
            if self.pending:
                stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
                self.log_stream.write(f"[{stamp}] {self.pending}\n")
                self.pending = ""
            if self.console_stream is not None:
                self.console_stream.flush()
            self.log_stream.flush()

    log_handle = LOG_PATH.open("a", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_handle)
    sys.stderr = Tee(sys.__stderr__, log_handle)
    try:
        if args.channels:
            return show_channels()
        if args.baseline:
            return do_baseline()
        if args.status:
            return show_status(load_json(STATE_PATH, {}))
        state = load_json(STATE_PATH, {})
        if args.retry_failures:
            changed = 0
            for item in state.get("queue", []):
                for name, status in item.get("targets", {}).items():
                    if status == "needs_attention":
                        item["targets"][name] = "retry"
                        item.get("attempts", {})[name] = 0
                        changed += 1
            save_json(STATE_PATH, state)
            print(f"Reset {changed} rejected destination(s) for another attempt. Uncertain results were left untouched.")
            return 0
        config = load_config()
        feeds = load_feeds()
        if not state.get("baseline_at"):
            raise RuntimeError("No baseline exists yet. Run setup_baseline.bat first.")
        added = poll_feeds(state, feeds, config)
        if added:
            print(f"Queued {added} new article(s).")
        elif state.get("last_check_result") == "not_due":
            print("The hourly feed check is not due yet; no feeds were fetched on this run.")
        else:
            errors = int(state.get("last_check_error_count", 0))
            checked = int(state.get("last_check_feed_count", 0))
            if errors:
                print(f"Checked {checked} feed(s); no new dated articles found. {errors} feed(s) returned errors.")
            else:
                print(f"Checked {checked} feed(s); no new dated articles found.")
        if args.dry_run:
            try_publish(state, config, dry_run=True)
        else:
            try_publish(state, config, dry_run=False)
        save_json(STATE_PATH, state)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
