# Changelog

All changes to Sunak, newest version first. Sunak shows the entries between your version and the new one **before** you install an update: in the app (Update button, Settings → Updates) and in the terminal (`sunak update`, `sunak changelog`).

Format: one section per version, `## [a.b.c] – YYYY-MM-DD`, followed by short points under **Added**, **Changed**, **Fixed** or **Removed**. Every change to Sunak gets a new version and an entry here.

## [0.16.0] – 2026-10-08

### Added
- Calendar reminders: the event form has a new "Reminder" field (at the start, 5 minutes up to 2 days before; for all-day events at 9:00 on the day or the days before). It is stored as a standard iCalendar reminder (`VALARM`), so it also works with CalDAV and shows up in other calendar apps. Reminders that events from CalDAV or ICS calendars already carry are used too.
- Reminders show as a notice in the page and, if you allow it, as a desktop notification while Sunak is open (Settings → Reminders, off by default).
- Push messages to your phone through ntfy (https://ntfy.sh or your own server), also when no browser is open, as long as Sunak is running. Set the topic in Settings → Reminders; "Random topic" makes a hard-to-guess one and "Send test" checks it. A failed push is tried again until the event starts. The topic is left out of the backup.
- New endpoints `GET /api/reminders` and `POST /api/reminders/test`; new module `sunak/reminders.py`; new settings `reminders`, `ntfy_url`, `ntfy_topic` and `reminder_lang`.

### Changed
- Changing an event keeps its other reminders (for example e-mail reminders set in another app); only the reminder chosen in Sunak is replaced.

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
