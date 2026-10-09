# Changelog

All changes to Sunak, newest version first. Sunak shows the entries between your version and the new one **before** you install an update: in the app (Update button, Settings → Updates) and in the terminal (`sunak update`, `sunak changelog`).

Format: one section per version, `## [a.b.c] – YYYY-MM-DD`, followed by short points under **Added**, **Changed**, **Fixed** or **Removed**. Every change to Sunak gets a new version and an entry here.

## [0.21.0] – 2026-10-09

### Added
- Security package. Wrong passwords and PINs are now counted: after 5 wrong tries from the same device the login and the PIN prompt lock for 30 seconds, and every further wrong try doubles the wait (up to 15 minutes). The installation's password and each profile's PIN also lock after 20 wrong tries from all devices together, so guessing from many addresses does not help. While locked, even the right password has to wait; the page says "Too many wrong attempts. Try again later." (HTTP 429 with `Retry-After`). A right answer starts counting again.
- Web search and Research read pages only from public internet addresses. Addresses of your own computer or network (`localhost`, `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16` including cloud metadata services, `::1`, `fc00::/7`, `fe80::/10`, IPv6 forms of these) are refused, also when a public-looking name points there and also after a redirect; such a page is simply skipped. The connection goes to the very address that was checked (the name is looked up once and the check applies to that answer, with the name kept for the Host header and TLS), so a name that answers differently the second time (DNS rebinding) gains nothing. Behind a system proxy the proxy looks the name up itself, so there only the check before the request applies. Your own SearXNG and Ollama on `localhost` keep working. `SUNAK_ALLOW_PRIVATE_FETCH=1` switches the protection off for research on an intranet.

### Changed
- An admin profile without a PIN can only be opened on the computer Sunak runs on as soon as there are other profiles. From a phone, the network or behind a reverse proxy its tile shows a lock and Sunak asks for a PIN to be set first (Settings → Profile). Devices that are already in the profile, single-profile setups and admin profiles with a PIN are unchanged. Settings → Profile explains this.
- `GET /api/profiles` has a new field `locked` per profile.
- "On the computer itself" is checked more strictly (also for `sunak stop` through the page): besides loopback and no `X-Forwarded-For`/`Forwarded`, the request must be addressed as `localhost` or an IP address and carry none of `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Real-IP`, `Via`, `CF-Connecting-IP`, `True-Client-IP`. A reverse proxy on the same computer that adds no such header cannot be told from a local visit, so it has to set `X-Forwarded-For` (nginx: `proxy_set_header X-Forwarded-For $remote_addr;`); the README says so.

### Fixed
- The login and PIN limits count an attempt before the slow password check, not after it, so a burst of parallel requests cannot get past the limit.

Note: because the password and each PIN also lock after 20 wrong tries from all devices together, someone guessing from many addresses can lock the owner out for up to 15 minutes (restarting Sunak clears it). This is a deliberate trade-off.

## [0.19.0] – 2026-10-09

### Added
- Slash commands in the chat. Type `/` at the start of the message box and a list of commands opens (arrow keys and `Tab` or `Enter` pick one, `Esc` closes it). Every command has a German and an English name: `/termin` (`/event`) prepares a calendar event as a card, `/mail` drafts an e-mail as a card, `/bild` (`/image`) paints a picture, `/web` answers with a web search, `/wissen` (`/knowledge`) answers from your knowledge base only, `/heute` (`/today`) and `/woche` (`/week`) show today's calendar or the next 7 days, `/modell` (`/model`) and `/persona` switch the model or persona of this chat, `/neu` (`/new`) starts a new chat (with an optional first message), `/export` downloads the chat (`md`, `json` or `print`), `/suche` (`/search`) searches all chats, `/zusammenfassen` (`/summarize`) summarizes the chat and `/hilfe` (`/help`) lists everything. The commands reuse what the chat already does; nothing is sent or saved without the usual click.
- `/web` and `/wissen` apply to that one message only: the chat's own switches (Web search, Knowledge base in the **+** menu) stay as they are. For this the chat request takes an optional `once` field (`POST /api/chat`: with `once: true`, `use_web` and `use_kb` count for this answer only and are not stored with the chat).
- A text that only looks like a path (`/etc/hosts`, `/Users/me/file.txt please read`) is still an ordinary message. An unknown command such as `/foo` is reported and not sent; with text after it (`/foo bar`) it goes to the model as it is.

## [0.18.0] – 2026-10-08

### Added
- Backups can be imported. Settings → Data has a new "Import backup" button next to "Download backup", and `sunak import FILE` does the same in a terminal (`--profile ID` picks the profile, default the main one; `--data-dir PATH` another data folder). It takes a backup file, or a single chat exported as JSON, and adds it to the profile you are in. Nothing is overwritten and nothing is added twice: chats, documents and notes with the same id (notes also with the same text), knowledge-base files with the same name, calendar events with the same id, mail accounts and calendar accounts with the same address are skipped, and a setting is taken over only when you have not set it yourself. Settings of the whole installation and model providers come in only from an admin profile; a profile never touches another profile's data.
- After an import Sunak says what was added, what was skipped (already there, or damaged) and which passwords and API keys you have to enter again (they are never part of a backup). Pictures are not part of a backup either, so chats come back without them.
- Imported chats are rebuilt from a safe subset: sources shown under an answer keep only http(s) links, and pictures, picture jobs and event or mail cards are dropped, so a backup from anywhere cannot add a harmful link or a spinner that never ends. Chats without an id are recognised by title, time and first message; a knowledge-base file with the same name but other text comes in as "name (imported)" instead of being skipped or replaced. A database error (for example a busy database) skips only the item it hit and the report says the import is partial.
- The links under web-search answers are shown only for http(s) addresses and a broken address no longer breaks the chat view; a chat with a picture whose file is missing shows a short note instead of failing.
- `POST /api/import` is the endpoint behind the button. A file that is not a Sunak backup is refused with a clear message; single damaged entries inside a backup are skipped and counted instead of stopping the import.

## [0.17.2] – 2026-10-08

### Changed
- Documentation brought up to date with the current code: README (busy backend in the model list, settings search) and docs/ARCHITECTURE.md (settings search in the frontend). No change in behavior.

## [0.17.1] – 2026-10-08

### Fixed
- The model list no longer blocks while a backend is busy. When the last list is known and the backend needs longer than 3 s, that list is shown at once and refreshed in the background, for every profile (before, it was kept only for the main profile and a timing-out backend could hold the picker for about half a minute). A refused connection or wrong key still shows the error and no old list.
- Fewer needless calendar notes in the chat: code questions ("event listener", cron "schedule", "busy-wait"), "Kalenderblatt in CSS", a song about Monday or a greeting like "Morgen!" no longer add the calendar. Questions like "Kann ich um 14 Uhr zum Zahnarzt?", "Wann habe ich Zeit für ein Treffen?" and "Do I have anything on at 3pm?" now do.
- Backticks are removed from event titles and places in that note, so an event in a shared calendar cannot fake a Sunak card. Events that began earlier and still run (a multi-day trip) are now included.

## [0.17.0] – 2026-10-08

### Added
- The chat model can now see your calendar (issue #13). When your message is about time or the schedule ("Was steht morgen an?", "Am I free on Friday?", "meine Termine diese Woche", weekday names, "today"), Sunak adds your appointments of today and the next 7 days to that request, read-only and from all calendars shown in the calendar (own, CalDAV, ICS), with times in your local time. Other messages get nothing, so no tokens are spent. Only the profile you are using is read. A calendar that cannot be read is named instead of being treated as empty. Event texts are marked as data, never as instructions. Works in the normal chat and in the tool loop, not in Compare.
- Settings has a search box at the top (issue #15). It hides every section and setting that does not match what you type, in English and German.

### Fixed
- Models no longer vanish from the model picker while a model is busy (issue #15). Asking the backend for its model list now waits longer (8 s, then once more up to 25 s when it only timed out) and keeps the list from the last success when the backend is still busy; the provider then shows "busy, last list shown" instead of "offline". The Ollama status check waits 10 s instead of 3–4 s. If no model can be loaded, the picker says "Models could not be loaded" and shows the reason on hover instead of "No model installed".

## [0.16.1] – 2026-10-08

### Fixed
- Asking the chat to create an appointment no longer fails with "I cannot add calendar entries" when the request is worded in a way the pattern recognition does not catch. The chat model is now told that Sunak can prepare events and e-mails; it answers with a short sentence and a hidden block, and Sunak shows the usual card (Save / Edit, Open in Mail). Nothing is saved or sent before you click.

### Added
- `POST /api/assistant/check` checks such a block (same rules as "Event from text" and the e-mail draft) before the card appears. The block is shown as text on the card, never as HTML. The pattern recognition from 0.15.x stays as the fast path for small models.
- Saving an event from a chat card checks the calendar first and says "Already in the calendar" instead of adding the same title and start twice (for example after a reload).
- The note for the model is only added to the normal chat and the tool loop, not to Compare, and the mail part only when a mail account is linked.
- A block inside a four-backtick code example stays text, a half-written block is hidden while the answer streams, and Copy leaves the block out.

## [0.16.0] – 2026-10-08

### Added
- Calendar reminders: the event form has a new "Reminder" field (at the start, 5 minutes up to 2 days before; for all-day events at 9:00 on the day or the days before). It is stored as a standard iCalendar reminder (`VALARM`), so it also works with CalDAV and shows up in other calendar apps. Reminders that events from CalDAV or ICS calendars already carry are used too.
- Reminders show as a notice in the page and, if you allow it, as a desktop notification while Sunak is open (Settings → Reminders, off by default). A reminder that came due while no page was open, or while Sunak was off, is shown in the next page that opens, as long as the event has not started.
- Push messages to your phone through ntfy (https://ntfy.sh or your own server), also when no browser is open, as long as Sunak is running. Set the topic in Settings → Reminders; "Random topic" makes a hard-to-guess one and "Send test" checks it. A failed push is tried again until the event starts. The topic is left out of the backup. The ntfy server address is a setting of the whole installation that only admin profiles can change (each profile has its own topic).
- New endpoints `GET /api/reminders` and `POST /api/reminders/test`; new module `sunak/reminders.py`; new settings `reminders`, `ntfy_url`, `ntfy_topic` and `reminder_lang`.

### Changed
- Changing an event keeps its other reminders (for example e-mail reminders or reminders relative to the end, set in another app); only the reminder shown in the form is replaced, and switching "All day" no longer clears it.

## [0.15.1] – 2026-10-08

### Fixed
- Events and e-mails from the chat no longer fire on ordinary messages: picture requests ("Erstelle ein Bild von einem Meeting") stay pictures, and sentences such as "Create an event loop in node", "Make me a meeting summary", "Remind me what we discussed", "Schreib mir eine Zusammenfassung dieser Mail" or "Please write an email template" are normal chats. An event request now needs a date or time, and the recognition works in two steps: an intent (verb or head such as "Termin am Freitag"), then exclusions that only look at the words around the object ("e-mail template", "meeting summary", "Event-Plan"). "Remind me what …" is no reminder.
- Requests that worked before still work: "add a dentist appointment tomorrow at 3pm", "Leg mir für Montag einen Termin beim Arzt an", addresses such as tom@example.com, "Could you write an email to Tom …?" and dates such as "am 12.10. um 9".

### Added
- Short forms without a verb: "Termin morgen 10 Uhr Zahnarzt", "Neuer Termin: Freitag 14 Uhr Friseur", "Meeting with Tom on Friday at 2pm", "Zahnarzt morgen um 10 eintragen".
- Every event and e-mail card has "Send as normal message", which sends your text to the model as a normal chat message when Sunak guessed wrong (it waits while the input box has text).
- The event card warns when the date is in the past.

## [0.15.0] – 2026-10-08

### Added
- Events and e-mails from the chat: write "trag mir morgen 10 Uhr Zahnarzt ein" or "schreib Anna eine Mail, dass ich später komme" (German and English) and Sunak prepares them as a card in the chat. The event card has Save and Edit, the mail card has "Open in Mail" and "Copy text". Nothing is saved or sent before you click; sending still needs the Send button and its confirmation in the Mail view.
- The request is recognized by rules (`sunak/intent.py`), so it works with any model, including small local ones without tool calling. Questions such as "What is on tomorrow?" or "How do I write an email to my boss?" stay normal chats, and picture requests are unchanged.
- New endpoints `POST /api/assistant/intent` and `POST /api/assistant/mail`. Events reuse `POST /api/calendar/parse`.
- Without a linked mail account the card says so and offers "Add mail account" instead of an error.

## [0.14.2] – 2026-10-08

### Fixed
- On Windows the changelog of an update was read with the system code page, so the en dash in `## [x.y.z] – date` broke and the newest entry was missing. Git output is now always read as UTF-8.

## [0.14.1] – 2026-10-07

### Changed
- All documentation is now in English: README and `docs/ARCHITECTURE.md`.

### Fixed
- Documentation checked against the code: the changelog and `sunak changelog`, the tool loop (`/api/tools`), the 20-profile limit, the real menu names of the English interface, the mail attachment name ("E-mail: subject") and the model filters on the Models page.
- The screenshots in `docs/` come from an early version; the README now says so.

## [0.14.0] – 2026-10-07

### Added
- Changelog: before an update, Sunak shows what changes. In the app, the Update button first opens the list of changes (install or cancel), and Settings → Updates shows it under "Check for updates now".
- `sunak update` shows the changes and asks "Install the update now? [y/N]". With `--yes` (or `-y`) and without a terminal (scripts, autostart, the Update button) it does not ask.
- `sunak changelog` shows the changes of the next update without installing anything; when Sunak is up to date, it shows those of the installed version.
- If `CHANGELOG.md` is missing or broken, the update still works and Sunak says "No changelog available".

## [0.13.1] – 2026-10-07

### Fixed
- Old chats show the commands and diffs of earlier tool steps again.
- Picture requests are painted again while MCP tools are on.
- German translation for the 30-step stop notice.

### Removed
- Unused agent strings.

## [0.13.0] – 2026-10-07

### Removed
- Agent mode: the folder tools, `/api/agent`, the agent toggle and its settings.

### Changed
- MCP tools now run through `/api/tools` (`sunak/toolrun.py`).

## [0.12.3] – 2026-10-07

### Fixed
- The speed test of the token counter no longer depends on the clock of the test machine (it failed on Windows).

## [0.12.2] – 2026-10-07

### Fixed
- Token counter: stopped Claude replies no longer produce placeholder output, a zero in `message_delta` no longer overwrites real numbers, `stream_options` is only retried when the server names them, and the output time of tool calls is counted.

## [0.12.1] – 2026-10-07

### Removed
- Token counter: the progress bar to 1,000,000,000 tokens.

## [0.12.0] – 2026-10-07

### Added
- Token counter per profile: for all providers and the agent, with tokens per second and the total.

## [0.11.1] – 2026-10-07

### Fixed
- The research test no longer reaches the real web search (it hung on macOS and Windows CI).

## [0.11.0] – 2026-10-07

### Added
- Picture requests are recognised in Deep Research too; every check is logged.
- Web search: search queries written by models (Qwen) are cleaned up, DuckDuckGo Lite and Bing serve as fallbacks, and Sunak says why a search failed.

## [0.10.1] – 2026-10-07

### Changed
- Error reports know that the repository is public: strict masking, warnings and a confirmation before automatic sending. The docs no longer assume a private repository.

## [0.10.0] – 2026-10-07

### Added
- The chat model checks picture requests (setting, on by default); clear requests are painted without a question.

## [0.9.4] – 2026-10-07

### Fixed
- Picture requests never fail silently: there is a hint when pictures are not set up or agent mode is on, and every check is logged.

## [0.9.3] – 2026-10-07

### Fixed
- Short picture requests without a verb are recognised ("a picture of: ...", "Bild von ...", "draw a cat").

## [0.9.2] – 2026-10-07

### Fixed
- Picture requests are recognised more reliably (rules plus the chat model for unclear messages).

## [0.9.1] – 2026-10-07

### Changed
- Docs: who needs a GitHub account for error reports.

## [0.9.0] – 2026-10-07

### Added
- Error reports as GitHub issues: opt-in, anonymised, with preview, duplicate detection and a rate limit.

## [0.8.1] – 2026-10-07

### Changed
- Docs: the a.b.c version policy.

## [0.8.0] – 2026-10-07

### Added
- Better logging in the terminal and in a log file of at most 50 MB (`sunak logs`).

## [0.7.1] – 2026-10-07

### Fixed
- The queue test no longer depends on thread start timing (it failed on macOS CI).

## [0.7.0] – 2026-10-07

### Added
- Picture requests in the chat are made automatically with an improved prompt.
- Requests to models run in a queue (first come, first served).

## [0.6.2] – 2026-10-07

### Changed
- Docs merged with the notes on the update check.

## [0.6.1] – 2026-10-07

### Changed
- Docs rewritten and checked against the code; the button for the update check is documented.

## [0.6.0] – 2026-10-07

### Added
- Settings → Updates: the "Check for updates now" button checks right away and gives the reason when it fails.

## [0.5.0] – 2026-10-07

### Changed
- Version number adjusted (0.4.0 was already taken by the memory feature).

## [0.4.0] – 2026-10-07

### Added
- Sunak remembers facts from chats by itself (memory).
- Composer options in a drop-up menu so the text field has room on phones.

## [0.3.0] – 2026-10-07

### Added
- Mail, own line icons instead of emojis, and guided image setup; the versioning rule is documented.

## [0.2.0] – 2026-10-06

### Added
- Knowledge base (documents with an own PDF reader, full-text search), chat search and export, personas.
- Autostart, desktop icon and `sunak stop`.
- Update hint with an Update button; Sunak updates with `git pull` in the clone.
- Several profiles with their own data, optional PIN and admin rights; themes; interface in German.
- Calendar (CalDAV, ICS), speech input and reading aloud, MCP tools, web search with sources, image understanding (vision), phone access with a QR code.
- Image generation (Automatic1111, ComfyUI and an own program with model downloads), GPU detection.
- `sunak uninstall`, a clearer `sunak -h` with help per command.
