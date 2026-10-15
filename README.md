# Antilogicalism Feed Watcher

A Windows tool that monitors selected philosophy RSS feeds and shares new articles to Antilogicalism’s Facebook Page and X account through Buffer, at a controlled pace.

## How it fits into Antilogicalism

Antilogicalism is a personal philosophy project built around writing, reading, and keeping thoughtful material in circulation. Its website brings together Joshua’s writing, a bookshelf of primary sources, and curated links to ideas and publications across the web. This watcher extends that curation to social media by finding new articles in the project’s selected feeds and sharing them with readers on Facebook and X.

The watcher does not publish articles on the website, copy their full text, or log in to Feedly or social media. Feedly supplies the OPML export that defines the source list; the watcher reads the RSS or Atom URLs in that file, and Buffer delivers posts to the connected accounts.

## How it works

1. **Read the source list.** `feeds.opml` contains the `Feeds` folder from the Feedly export, currently 84 philosophy sources. The watcher fetches the feed URLs directly and parses them with Python’s `feedparser` dependency.
2. **Establish a baseline.** The one-time baseline marks articles already present as seen, so setup does not publish a backlog. It creates `state.json` and never sends posts.
3. **Find new articles.** Each feed is checked hourly by default. New items must have a publication date later than the baseline and be within the 30-day age limit. Undated and stale items are marked seen but not queued. Canonicalized article links help prevent duplicates from tracking parameters.
4. **Queue and publish at a measured pace.** The queue is ordered with older eligible articles first. The watcher sends at most one article per run and tracks Facebook and X separately; an article leaves the queue only after both channels accept it.
5. **Keep a local record.** `state.json` stores the baseline, seen links, queue, and destination statuses. `watcher.log` records feed errors and publishing results so the task can resume and be checked later.

Posts contain the title, an optional `By: Author` line when a feed supplies an author, and the feed name as the source. X also gets the article URL. Facebook gets a regular post with a link attachment built from the article page’s Open Graph metadata when available, allowing Buffer to show its title, description, and image.

## Pacing and delivery behavior

Windows Task Scheduler runs the watcher every 15 minutes to see whether a feed poll or queued post is due. By default, each feed is fetched once an hour, there is a two-hour minimum between accepted articles, and no more than five articles are released per day.

Rejected posts remain queued for retry after the configured wait. Authentication, permission, or invalid-post errors need attention. If the watcher loses the response after submitting to Buffer, it marks that destination’s result uncertain and does not retry automatically, since Buffer may already have accepted the post. This reduces the chance of duplicates while leaving the item available for manual review.

The scheduled task uses `pythonw.exe` and runs quietly without a console window. The computer must be awake, connected to the internet, and the configured Windows user must be logged in. Sleep or shutdown pauses checks; the queue resumes at the same controlled pace when the task runs again.

## Setup

### Requirements

- Windows with Python 3.10 or newer. Install Python with “Add Python to PATH” enabled.
- Internet access and a Buffer account with the intended Facebook Page and X account connected.

### Install and connect

1. Download or clone the repository into a permanent folder.
2. Run `setup.bat` to create the local `.venv` and install the dependency from `requirements.txt`.
3. Run `setup_baseline.bat` once. It checks the feeds, marks current articles as seen, and creates `state.json`. The baseline does not publish anything and refuses to overwrite existing state.
4. Run `create_env.bat` and put your Buffer API key after `BUFFER_API_KEY=` in the resulting `.env` file.
5. Copy `config.example.json` to `config.json`. Run `list_buffer_channels.bat` to find the Buffer channel IDs, then enter the Facebook Page ID and X channel ID in `config.json`.
6. Keep `publishing_enabled` set to `false` while you use `preview_queue.bat` to inspect the next queued article. Once settings and the preview look right, enable publishing, run `run_once.bat`, and confirm both posts in Buffer and on the social pages.
7. Run `install_task.bat` to install the quiet 15-minute task.

For a fresh install, establish the baseline before enabling publishing. Keep `state.json`; deleting it loses the seen-item history and any queued posts.

## Configuration

Edit the local `config.json`, which is created from `config.example.json`. Defaults are conservative:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `publishing_enabled` | `false` | Must be deliberately enabled before any post can be sent. |
| `facebook_channel_id`, `x_channel_id` | empty | Buffer destinations for the Facebook Page and X account. |
| `poll_interval_minutes` | `60` | Minimum interval between checks of each feed. |
| `minimum_hours_between_articles` | `2` | Minimum time between accepted articles. |
| `max_articles_per_day` | `5` | Daily publishing cap. |
| `max_auto_retries` | `3` | Maximum attempts for a rejected destination before manual review. |
| `retry_wait_minutes` | `60` | Wait before retrying a rejected post. |
| `max_age_days_for_new_items` | `30` | Excludes old articles discovered after a feed repair. |

## Checking and controlling the watcher

| File | What it does |
| --- | --- |
| `preview_queue.bat` | Shows the next queued article without publishing. |
| `check_status.bat` | Shows the baseline, latest poll, queue size, and feeds with errors. |
| `run_once.bat` | Checks due feeds and processes at most one queued article. |
| `list_buffer_channels.bat` | Lists connected Buffer channel IDs. |
| `retry_failures.bat` | Re-enables rejected posts for another attempt after the issue is fixed; uncertain results remain untouched. |
| `uninstall_task.bat` | Removes the scheduled task. |

The matching command-line options are `--baseline`, `--dry-run`, `--status`, `--run-once`, `--channels`, and `--retry-failures`; pass one option per run. Review `watcher.log` for the details from scheduled runs.

## Files, privacy, and limits

The Buffer key belongs in `.env`; channel IDs and personal settings belong in `config.json`. The repository’s `.gitignore` excludes those files along with `state.json`, `watcher.log`, and the Python environment. Commit the blank `.env.example` and `config.example.json` templates, not your local credentials or account configuration. `feeds.opml` contains the selected source list.

The watcher depends on each site maintaining a reachable RSS or Atom feed. Some sources may block automated requests, change feed URLs, or omit publication dates; those issues appear in the status output and log. Facebook previews depend on usable Open Graph metadata from the article site, and Buffer’s API and channel permissions may change. Check both destinations after the first live post and after significant account or configuration changes.

