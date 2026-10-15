# Antilogicalism Feedly → Buffer watcher

This Windows package watches the `Feeds` folder from your Feedly OPML export and can cross-post new article links to one Facebook Page and one X/Twitter channel through Buffer. It is a local program; it does not log in to Feedly or either social network.

## What it does

- Starts from the 84 sources in the exported `Feeds` folder.
- Takes a one-time baseline, marking current feed items as already seen so it will not publish an old-article dump.
- Checks feeds hourly when the scheduled task runs every 15 minutes.
- Keeps a local queue and sends no more than one article per run, with a two-hour minimum gap and a five-article daily cap by default.
- Keeps an article queued until both selected channels have accepted it. If a request times out after submission, it marks that destination uncertain and will not retry it automatically, avoiding a likely duplicate.
- Defaults to publishing disabled. No post can be sent until you have configured both channel IDs and deliberately set `publishing_enabled` to `true`.
- Stores the queue, seen links, and log beside the program in `state.json` and `watcher.log`.

## First setup

1. Install Python 3.10 or newer for Windows if it is not already installed. Keep “Add Python to PATH” enabled.
2. Unzip the package into a permanent folder, such as `Documents\AntilogicalismFeedWatcher`.
3. Double-click `setup.bat`. It creates a private Python environment and installs the RSS parser.
4. Double-click `setup_baseline.bat` once. It fetches the current 84 feeds, marks the articles it can read as seen, and creates `state.json`. **It does not publish anything.** Some feeds returned errors during the initial audit; those are recorded and retried on later checks.

The baseline requires an internet connection. Do not delete `state.json`: it contains the seen-item history and queue. The baseline refuses to overwrite an existing state file.

## Connect Buffer when ready

1. Create or sign in to Buffer and connect the intended Facebook Page and X/Twitter account.
2. Double-click `create_env.bat`; it creates and opens `.env`. Paste a Buffer API key after `BUFFER_API_KEY=`. Keep `.env` private and never commit it to GitHub.
3. Copy `config.example.json` to `config.json`. Double-click `list_buffer_channels.bat` (after adding a Buffer key) to list connected channel IDs, then enter the Facebook Page ID and X/Twitter channel ID in `config.json`. The local `config.json` is ignored by Git; commit only the example file.
4. Leave `publishing_enabled` set to `false` for the first preview. Double-click `preview_queue.bat` to verify what would be sent. It does not publish.
5. Once the channel IDs and preview are correct, set `publishing_enabled` to `true` in `config.json`. Run `run_once.bat` and verify the two posts in Buffer/social pages before installing the schedule.
6. Double-click `install_task.bat` to check every 15 minutes. Feed fetching is limited to once an hour. You can remove the task with `uninstall_task.bat`.

When the computer is asleep or off, checks pause. After it wakes, the queue drains at the configured pace instead of posting the backlog all at once. If you want to stop publishing temporarily, set `publishing_enabled` to `false` or disable the scheduled task in Task Scheduler.

## Handy controls

- `preview_queue.bat` — show the next queued article without posting.
- `check_status.bat` — show queue size and the number of feeds with recent errors.
- `run_once.bat` — poll feeds if due, then process at most one article.
- Run `.venv\Scripts\python.exe watcher.py --channels` to list Buffer channels after adding the API key.
- Run `.venv\Scripts\python.exe watcher.py --retry-failures` after fixing a rejected post's configuration. Uncertain network outcomes are never reset by this command.
- Edit `config.json` to change poll interval, pacing, daily cap, or age cutoff.

If you preview right after the baseline, an empty queue is expected. The first new feed check is due about an hour later; the program now says whether it actually fetched feeds or is waiting for the hourly check.

## Files and privacy

- `.env`: Buffer API key; excluded from Git by `.gitignore`.
- `state.json`: deduplication state and post queue; excluded from Git.
- `watcher.log`: run history and errors; excluded from Git.
- `feeds.opml`: the 84-source `Feeds` folder only.

## Current constraints

- The first implementation checks RSS/Atom feeds directly, so some feeds may block automated requests or require URL repair. Feed errors appear in the status summary and log.
- New items need a publication timestamp and must be newer than the baseline and no more than 30 days old. This prevents importing old feed history after a broken source is repaired.
- Posts show the article title, an optional `By: Author` line when the feed provides an author, and `Source: Feed name`. X also includes the article URL; Facebook uses the article's link card for the URL and preview image. Missing author data is omitted cleanly.
- Buffer API behavior and channel permissions can change. The first live test must be checked in Buffer before letting the scheduled task run unattended.
