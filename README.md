# Antilogicalism Feed Watcher

A Windows tool that monitors selected philosophy RSS feeds and shares new articles to Antilogicalism’s Facebook Page and X account through Buffer, at a controlled pace.

## How it fits into Antilogicalism

Antilogicalism is a personal philosophy project built around writing, reading, and keeping thoughtful material in circulation. Its website brings together Joshua’s writing, a bookshelf of primary sources, and curated links to ideas and publications across the web. This watcher extends that curation to social media by finding new articles in the project’s selected feeds and sharing them with readers on Facebook and X.

The watcher does not publish articles on the website, copy their full text, or log in to Feedly or social media. Feedly supplies the OPML export that defines the source list; the watcher reads the RSS or Atom URLs in that file, and Buffer delivers posts to the connected accounts.

## How it works

1. **Read the source list.** `feeds.opml` contains the `Feeds` folder from the Feedly export, currently 84 philosophy sources. The watcher fetches the feed URLs directly and parses them with Python’s `feedparser` dependency.
2. **Establish a baseline.** The one-time baseline marks articles already present as seen, so setup does not publish a backlog. It creates `state.json` and never sends posts.
3. **Find new articles.** Each feed is checked hourly by default. New items must have a publication date later than the baseline and on the current local calendar day. Undated, older, or prior-day items are marked seen but not queued. Canonicalized article links help prevent duplicates from tracking parameters.
4. **Filter lightly, then rank.** The selected Feedly folder is already curated, so fresh articles pass by default. The watcher holds back only clear everyday personal-activity posts, such as a diary-style weekend update or a cat-shelter visit. Announcements, roundups, and articles without familiar topic keywords can still pass. Topic matches in the title, summary, and categories affect ranking only: they help philosophy, science, literature, and culture pieces rise earlier in the queue, but they are not an eligibility test. Gregory Sadler and Arts & Letters Daily receive a modest three-point source bonus; Quanta Magazine keeps its two-point bonus. If a Sadler article was among the last three completed posts, another source is chosen while an eligible alternative exists. Repeated posts from other exact feed sources receive a small score penalty. An article already accepted by one channel is finished first, so cross-posts remain together. The watcher sends at most one article per run and tracks Facebook and X separately; an article leaves the queue only after both channels accept it.
5. **Keep local records.** `state.json` stores the baseline, seen links, queue, and destination statuses. `watcher.log` records feed errors and publishing results with local timestamps and timezone offsets. `rejected_articles.csv` records items skipped because of publication age/date or the personal-activity filter. It is de-duplicated by article URL and opens in a spreadsheet app for review. The log also records topic matches and ranking scores for discovered items; an absent topic match does not block an article. When an Arts & Letters Daily item has no RSS date, the watcher checks common publication-date metadata on the linked article page and records whether the date came from the feed or the page.

Posts contain the title, an optional `By: Author` line when a feed supplies an author, and the feed name as the source. X also gets the article URL. Facebook gets a regular post with a link attachment built from the article page’s Open Graph metadata when available, allowing Buffer to show its title, description, and image.

## Pacing and delivery behavior

Windows Task Scheduler runs the watcher every 15 minutes to see whether a feed poll or queued post is due. By default, each feed is fetched once an hour, there is a one-hour minimum between accepted articles, and no more than fifteen articles are released per local day. Articles must be newer than the baseline and no more than twelve hours old when queued or posted. This short rolling window catches late-evening articles that the next poll sees after midnight, while preventing a multi-day backlog. Items older than twelve hours are discarded. If more than fifteen fresh articles arrive in one local day, or the pacing gap prevents them from clearing before they expire, the remainder will be skipped rather than posted late.

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
| `minimum_hours_between_articles` | `1` | Minimum time between accepted articles. |
| `max_articles_per_day` | `15` | Daily publishing cap. |
| `max_auto_retries` | `3` | Maximum attempts for a rejected destination before manual review. |
| `retry_wait_minutes` | `60` | Wait before retrying a rejected post. |

## Checking and controlling the watcher

| File | What it does |
| --- | --- |
| `preview_queue.bat` | Shows the top eligible articles with relevance scores and reasons, without publishing. |
| `review_rejections.bat` | Opens `rejected_articles.csv` to review articles held back by the publication-date or personal-activity filters. |
| `check_status.bat` | Shows the baseline, latest poll, queue size, and feeds with errors. |
| `run_once.bat` | Checks due feeds and processes at most one queued article. |
| `list_buffer_channels.bat` | Lists connected Buffer channel IDs. |
| `retry_failures.bat` | Re-enables rejected posts for another attempt after the issue is fixed; uncertain results remain untouched. |
| `uninstall_task.bat` | Removes the scheduled task. |

The matching command-line options are `--baseline`, `--dry-run`, `--status`, `--run-once`, `--channels`, and `--retry-failures`; pass one option per run. Review `watcher.log` for the details from scheduled runs.

## Files, privacy, and limits

The Buffer key belongs in `.env`; channel IDs and personal settings belong in `config.json`. The repository’s `.gitignore` excludes those files along with `state.json`, `watcher.log`, `rejected_articles.csv`, and the Python environment. The rejection report starts collecting when this feature is installed; it cannot reconstruct articles rejected before then. Commit the blank `.env.example` and `config.example.json` templates, not your local credentials or account configuration. `feeds.opml` contains the selected source list.

The watcher depends on each site maintaining a reachable RSS or Atom feed. Some sources may block automated requests, change feed URLs, or omit publication dates; those issues appear in the status output and log. Facebook previews depend on usable Open Graph metadata from the article site, and Buffer’s API and channel permissions may change. Check both destinations after the first live post and after significant account or configuration changes.

