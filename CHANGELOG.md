# Changelog

All changes to Sunak, newest version first. Sunak shows the entries between your version and the new one **before** you install an update: in the app (Update button, Settings → Updates) and in the terminal (`sunak update`, `sunak changelog`).

Format: one section per version, `## [a.b.c] – YYYY-MM-DD`, followed by short points under **Added**, **Changed**, **Fixed** or **Removed**. Every change to Sunak gets a new version and an entry here.

## [0.14.3] – 2026-10-08

### Fixed
- Windows: Sunak did not start from the desktop icon, the Start menu or autostart, because those start it without a console and the color check expected one. Output to a redirected console (`sunak -h | more`) also no longer crashes on symbols such as the sailboat.
- Public error reports: the error message was cut to 200 characters before its private parts were masked, so a cut could leave half an e-mail address or an unfinished quote in a public issue. It is now masked first. Addresses in `http://user:password@host` links and e-mail addresses cut off in the middle are masked as well.
- `sunak uninstall` rewrote shell start files (`~/.bashrc` and similar) as UTF-8 with LF line endings; a file in another encoding or with Windows line endings came back damaged. Only the Sunak PATH line is removed now, everything else stays byte for byte.
- Image generation: the program list could offer macOS builds on Windows (`darwin` contains `win`) and Intel builds on Apple silicon; a model whose name starts like a downloading one was refused as "still downloading".
- Model and program downloads: a full disk or a missing permission is now reported instead of ending the download silently.
- Knowledge base: a PDF with a very long run of digits could freeze the upload for minutes; very long texts made the search words and the chunking slow (quadratic).
- Calendar: a lone carriage return in a title or description could add extra lines to the event file; an event address in a sibling folder with a similar name (`/cal2` for `/cal`) is no longer accepted. Truncated or malformed server answers (calendar, MCP, speech) are reported as errors instead of crashing the request.
- MCP: a tool call to a server that had just exited waited for the five minute timeout; it now fails at once. A closed connection no longer ends the whole answer with an internal error.
- Mail: folder names with line breaks are refused. Speech: the language code is checked before it is sent.

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
