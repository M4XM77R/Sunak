# Sunak architecture

Sunak is a single Python process. It serves the web interface, provides a JSON API and talks to the AI backends. There are no Python dependencies and no build step for the frontend.

```
Browser (sunak/static)  ──HTTP/JSON, NDJSON streams──▶  sunak/server.py
                                                          │
                     ┌────────────────────┬───────────────┼──────────────────┐
                     ▼                    ▼               ▼                  ▼
               sunak/db.py         sunak/providers.py  sunak/research.py   File system
               SQLite file         Ollama / OpenAI API  DuckDuckGo/SearXNG  (static/)
```

## Files

| File | Purpose |
|---|---|
| `sunak/__main__.py` | Command line (`python -m sunak`): opens an already running Sunak in the browser, otherwise looks for a free port, starts the server and opens the browser. Commands `status`, `stop`, `update`, `changelog`, `version`, `gpu`, `logs`, `mail-selftest`, `autostart on\|off\|status`, `shortcut`, `uninstall`, `help`; start options `--port`, `--host`, `--data-dir`, `--no-browser`, `--version`. All of them are listed with group, short text and example in `COMMANDS`; that produces `sunak -h`, `sunak <command> -h` and the "Did you mean …?" hint for typos. Colors only in a terminal and without `NO_COLOR` |
| `sunak/gpu.py` | GPU detection without extra packages: `nvidia-smi`, `/sys/class/drm` (Linux), registry (Windows), Apple Silicon; evaluation of Ollama's `/api/ps` and a warning when running on the CPU |
| `sunak/changelog.py` | Reads `CHANGELOG.md`: `parse` (sections `## [a.b.c] – date`), `between` (entries between the installed and the new version, newest first), `to_text` (terminal). A broken or missing file means no entries, never an error |
| `sunak/updates.py` | Update check via git (new commits in the clone the installation came from, plus the changelog of the remote) and the helper process for the update button: waits for the server to end, installs the update, restarts Sunak |
| `sunak/desktop.py` | Desktop integration: detect a running Sunak (`/api/status` with `Server: Sunak/…`) and stop it, autostart file and desktop icon per operating system |
| `start.py` | Start directly from the repository folder without installing (Windows: double click) |
| `sunak/server.py` | `App` (state, settings, model selection, login, prompt construction) and `Handler` (HTTP routing, all API endpoints) |
| `sunak/db.py` | SQLite storage: chats, messages, documents, notes, settings |
| `sunak/providers.py` | Backends: Ollama, Claude (Anthropic Messages API) and OpenAI-compatible APIs, streaming, model download |
| `sunak/ollama.py` | Native Ollama integration: model catalog, status, find, start and install a local Ollama |
| `sunak/research.py` | Web search, reading pages, prompt for the research report |
| `sunak/toolrun.py` | Tool loop in the chat: tool calling per backend, text protocol as a fallback, loop with approvals for the MCP tools |
| `sunak/extract.py` | Text from uploaded files: PDF (own reader), .docx, .odt, .pptx, HTML, text |
| `sunak/mail.py` | Mail: check accounts, IMAP (folders, list, search, mail as text, attachments, drafts, move, delete, new mail) and SMTP (send with attachments), provider presets, prompts for the AI |
| `sunak/mailtest.py` | `sunak mail-selftest`: check a real account step by step, only with its own test mails |
| `sunak/images.py` | Pictures in the chat: validation (file signature, size, count), storage in `<data>/images`, attaching to the messages for the model, cleanup |
| `sunak/qr.py` | QR code generator without dependencies, for phone access |
| `sunak/cal.py` | Calendar: read and write iCalendar, recurrences (RRULE, EXDATE, moved events), time zones, CalDAV client (find calendars, read, create, change, delete events), ICS subscriptions, event from text via the model |
| `sunak/mcp.py` | MCP client: start servers as a program (stdio) or over HTTP (Streamable HTTP), list and call tools, validate settings (secrets stay on the server) |
| `sunak/intent.py` | Recognizes picture requests in the chat: `classify` returns `yes` (a verb such as generiere/erstell/mach/mal/zeichn/draw/make plus a picture word such as Bild/Foto/Logo/picture/image, or a short form without a verb such as "a picture of: …" or "Bild von …", or a direct drawing command such as "draw a cat" or "zeichne einen Drachen"; in each case not a question, no technical word, not "ich mache …"), `maybe` (only a drawing verb at the start such as "mal mir eine Katze", a picture word with a request, a question or technical form) or `no`; `maybe` and `no` lead to a picture only through a YES from the chat model (if it cannot answer, they are a normal chat); `messages`/`parse` are the yes/no question to the chat model, `subject` is the description without the request (fallback prompt); `action` recognizes requests to prepare a calendar event ("trag mir morgen 10 Uhr Zahnarzt ein", "add … to my calendar", "remind me …") or an e-mail ("schreib Anna eine Mail …", "email Anna that …") by rules only: commands and polite requests count; questions, reports ("ich habe …"), technical words, words like template/tips, anything `classify` calls a picture request and more than 600 characters do not; two steps: an intent (mail verb … "Mail", "trag … ein", create verb … "Termin", "remind me", or a head such as "Termin am Freitag" / "Meeting with Tom on Friday") and, for events, a date or time (`_TIME`) unless the calendar is named; then exclusions that only look at the words between verb and noun (`_BEFORE_NOT`) and the word after it (`_AFTER_NOT`, hyphenated compounds), so "make a meeting summary" or "write an e-mail template" are no requests; "remind me what …" is none either; `addresses` finds e-mail addresses in a text |
| `sunak/imagegen.py` | Image generation: Automatic1111 (`/sdapi/v1/txt2img`, progress, cancel) and ComfyUI (default workflow via `/prompt`, `/history`, `/view`), image sizes, model list |
| `sunak/log.py` | Logging: one logger `sunak` with parts (`sunak.http`, `sunak.queue`, `sunak.image`, `sunak.app`, `sunak.main`); `setup(data_dir)` attaches two handlers: terminal (stderr, colors only in a terminal and without `NO_COLOR`) and `<data folder>/logs/sunak.log` (`RotatingFileHandler`, 10 MB per file, four backups, at most 50 MB in total, file readable only by the user). `redact` masks secrets in every line (`add_secret` for the providers' API keys, plus patterns for `password=…`, bearer tokens, `sk-…`, `?key=…`, long hex strings). Without `setup` (tests) the logger stays silent |
| `sunak/usage.py` | Token counter. `Meter` collects the numbers of one model request (`tick` for every output part, `put` for the backend's numbers: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `eval_ns`) and stores a record at the end (`finish`, only once, catches every error and logs only at DEBUG). Missing numbers are NULL. Tokens per second: `eval_count / eval_duration * 1e9` (Ollama), otherwise `output_tokens` divided by the time between the first and last output part (only if over 50 ms), otherwise NULL. Adapter helpers: `ollama_usage`, `openai_usage` (`prompt_tokens` includes `cached_tokens`; these are shown as cache read and subtracted from the input so that nothing is counted twice), `anthropic_usage` (`message_start` delivers input and cache but only a placeholder for the output, which is not adopted; the final output comes from `message_delta`. A 0 in `message_delta` does not replace an input or cache number that is already known, as some proxies send it. A stream that ends after `message_start` (stop, abort) has the output NULL and `ok` = 0 (`Meter.partial`)). All three helpers catch every error (`_safe`) and check the types so that an unusual answer never reaches the stream. The database and the kind of request come from a `ContextVar` (`bind`; `Handler.dispatch` sets it per request after the profile is chosen, `usage_kind` derives the kind from the path: `chat`, `tools`, `research`, `compare`, `document`, `mail`, `calendar`; background: `image_prompt`, `image_check`, `memory`). Threads that call models start via `usage.thread` and so keep the context (Compare, picture check). `summary` returns `last` (the last non-background request), `total` and `background` |
| `sunak/reports.py` | Error reports as GitHub issues (off by default, `error_reports` = `off`/`ask`/`auto`). `_Hook` (a `logging.Handler` from ERROR up, which `attach(app)` hangs on the logger `sunak`) hands every error logged with a traceback to `Reports.capture`; `__main__` also routes crashed background threads there (`threading.excepthook`). `build` turns it into a title and Markdown (version, system, Python, error, stack trace only with Sunak source lines and without variable values, `log.recent`); the issues are public, so `anonymize` is strict: private paths including file names (`<path>`), user and computer name, hosts in addresses except `SAFE_HOSTS` (`<host>`), `*.local`/`*.lan`, IPv4, IPv6, MAC, email, long quotes (`<text>`), then `log.redact`; the error text is cut to 200 characters. `fingerprint` = SHA-1 of the kind of error and the last four Sunak functions (without line numbers and text). `Reports` keeps waiting and sent reports in `<data folder>/reports.json` and sends through the GitHub REST API (`urllib`, bearer token): an issue with the fingerprint in the title (`(fp)`; label `auto-report`, which GitHub may silently drop without push permission, which is why `find_issue` searches through the titles of the last 300 issues); for an open issue only a comment (at most one per error and day, ten per day); for a closed one a new issue with a reference; at most `MAX_ISSUES_PER_HOUR` (3) new issues per hour. The token is stored in `settings.report_token` of the main database, never goes to the browser, the export or the log (`log.add_secret`). `issue_url` builds the pre-filled browser address (at most about 6000 characters). `SUNAK_REPORT_REPO` changes the repository |
| `sunak/jobqueue.py` | FIFO queue for model requests: one `Gate` per backend (`chat:<provider id>`, `image`) with `slots` places and a line of waiting requests; `slot(key, slots, notify, cancelled)` is a context manager. Waiting requests get `notify(place)` every two seconds (0 = its turn); if that fails (browser gone), the request leaves the line (`Cancelled`, a `BrokenPipeError`, so that the existing abort handling applies). `MAX_WAIT` 900 s (`Timeout`). Whoever already holds a place in the same line (same thread) does not wait for themselves. Local backends have `SUNAK_MODEL_SLOTS` (1) places, backends on the internet `REMOTE_SLOTS` (4) |
| `sunak/sdcpp.py` | Own image program: stable-diffusion.cpp from the GitHub releases (the right file per system and graphics card), image model catalog with licenses, downloads with resume (HTTP Range), generate an image via the command line |
| `sunak/modelsearch.py` | Model search in the Ollama library (ollama.com) and on Hugging Face (repositories, files with size, quantization, license) |
| `sunak/speech.py` | Voice input: pass the recording to a local Whisper server (whisper.cpp or OpenAI-compatible) |
| `sunak/knowledge.py` | Knowledge base: build sections, search, select matching sections for the chat |
| `sunak/memory.py` | Automatic memory: facts about the user from the last exchange, without secrets and duplicates |
| `sunak/static/` | Interface: `index.html`, `app.js` (all logic), `app.css` (including themes), `theme.js` (sets the theme before the first paint), `icons.js` (own icons), `i18n.js` and `lang-de.js` (languages), `login.html`, icon, PWA manifest |
| `tests/` | Tests, one file per area (see section Tests) |
| `.github/workflows/test.yml` | CI: the tests on Linux, macOS and Windows for every push and pull request |
| `install.sh`, `install.ps1` | Installers for macOS/Linux and Windows |
| `sunak/uninstall.py`, `uninstall.sh`, `uninstall.ps1` | Uninstallation (`sunak uninstall`); the scripts find the installed Sunak or download it and call the same Python module |
| `Dockerfile`, `docker-compose*.yml` | Container with Ollama: CPU only (`docker-compose.yml`), NVIDIA (`+ docker-compose.gpu.yml`) or AMD/ROCm (`+ docker-compose.amd.yml`) |

## Data flow of a chat message

1. `app.js` creates a chat if needed (`POST /api/sessions`) and sends the message to `POST /api/chat`.
2. `Handler.chat` stores the message and resolves the model ID `provider::model` via `App.resolve`.
3. `App.build_messages` assembles the history: system prompt from the settings, prompt of the chat's persona, prompt of the chat, notes tagged "memory", with the knowledge base switched on the matching excerpts (see below) and then the earlier messages. Thought processes (`<think>…</think>`) are removed in the process.
4. `providers.chat_stream` streams the answer as pairs `("think" | "text", piece)`.
5. The server passes every piece on to the browser immediately as an NDJSON line, for example `{"type": "text", "t": "Hello"}`.
6. At the end the answer is stored. The thought process stays embedded in `<think>` tags. If the connection drops, the partial answer is kept.
7. After that `app.js` calls `POST /api/sessions/<id>/remember` (not with tools, not after pictures and not when memory is switched off). `memory.extract` lets the chat's model draw lasting facts from the last question and answer; new ones become notes with `is_memory = 1` and `source` = chat ID. Without "Remember things about me from chats by itself" (`auto_memory`) this happens only when the user explicitly writes "merk dir …" / "remember that …". The browser shows what was remembered with Undo.

"Regenerate" and "Edit" send `truncate_from`. The server then deletes that message and all later ones before answering.

**Pictures:** The browser shrinks pictures to at most 1568 pixels on the long side (larger or long photos as JPEG) and sends them as `images: [{name, data}]` (Base64). `prepare_chat` checks before storing: file signature PNG, JPEG, GIF or WebP (the name does not count), at most 5 MB per picture and 4 pictures per message, and whether the model sees pictures (`App.vision`: Claude yes, Ollama according to `capabilities` from `/api/show`, OpenAI-compatible unknown). A model without image understanding gets a 400 response before anything is stored; the browser then puts text and pictures back into the input box. The files are stored as `<data>/images/<id>.<type>`, the message names them in `meta.images`, `GET /api/images/<name>` serves them. When editing, the browser sends the names as `image_refs`. `images.attach` attaches the pictures of the last three messages that have pictures (`message["images"] = [{type, data}]`); older ones and those for models without image understanding become a short note in the text. `providers` implements this per backend: Ollama `images` (Base64), Claude content blocks `image` before the text, OpenAI-compatible `image_url` with a data URL. If the request fails on an OpenAI-compatible backend, the error message adds a hint about image understanding. Pictures without a message (chat deleted, message replaced) are deleted by `App.clean_images` as soon as they are older than an hour.

## API

All endpoints live under `/api/`. Writing requests need the header `X-Requested-With: sunak`, which protects against CSRF. If a password is set, the cookie `sunak_token` is also needed.

| Method and path | Purpose | Response |
|---|---|---|
| `GET /api/status` | Version, login status, RAM, recommended model | JSON |
| `GET /api/update` | Update available? (`available`, `behind`, `version`, `current`, `changelog`, `can_update`, `result` of the last update, shown once); triggers the check in the background | JSON |
| `GET /api/usage` | Token counter of the profile: `last` (record with `ts`, `provider`, `model`, `kind`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `seconds`, `tokens_per_second`, `ok`; unknown numbers `null`), `total` and `background` (sums: `requests`, the four counters, `all` = sum including cache); admin profiles additionally `installation` (sum of all profiles) | JSON |
| `GET /api/reports`, `POST /api/reports/token`, `/check`, `/send`, `/dismiss`, `/sample` | Error reports (all admin only): state (`mode`, `token_set`, `repo`, waiting `pending` with text and browser `url`, most recent `sent`), store token (`{token}`, empty deletes; the response never contains it), check access, send one waiting report (`{id}` = fingerprint; response `url`, `number`, `action` = `created`/`commented`), discard, create a sample report. `GET /api/settings` tells admins `reports_pending` | JSON |
| `POST /api/update/check` | Button "Check for updates now" (admin): checks immediately, even when the notice is switched off, with the same check (`updates.inspect`) and updates its result. Response: `behind`, `available`, `known` (false = check not possible), `version` (version on the remote), `current`, `changelog` (list of `{version, date, body}`, `body` is Markdown), `error` (`no_clone`, `no_remote`, `no_upstream`), `can_update` | JSON |
| `POST /api/update` | Update button: starts the helper process and ends the server | JSON |
| `POST /api/shutdown` | End the server (`sunak stop`, button in Settings); from this computer without login, from other devices and through a reverse proxy (`X-Forwarded-For`, `Forwarded`) only when logged in | JSON |
| `POST /api/login`, `POST /api/logout` | Log in, log out | JSON |
| `GET`/`PUT /api/settings` | Settings and providers | JSON |
| `GET /api/models` | Models of all providers, plus errors of unreachable providers | JSON |
| `GET /api/ollama` | Ollama status (installed, running, version), installed models with size, catalog with `fits` and `gpu`, installation route, GPU (`gpu`, `gpu_expected`), loaded models with GPU share (`loaded`), `gpu_warning` | JSON |
| `POST /api/ollama/start` | Start a local Ollama in the background | JSON |
| `POST /api/ollama/install` | Install Ollama via winget or Homebrew | NDJSON `status` |
| `POST /api/models/pull` | Download an Ollama model; progress of all layers summed | NDJSON `progress` (`completed`, `total` in bytes) |
| `POST /api/models/delete` | Delete an Ollama model | JSON |
| `GET`/`POST /api/sessions`, `GET`/`PATCH`/`DELETE /api/sessions/<id>` | Chats (`use_kb`, `use_web`, `persona`, title, model, system prompt) | JSON |
| `POST /api/sessions/<id>/remember` | Automatic memory without a body: the chat's model draws lasting facts from the last question and answer; response `{added: [notes]}` (on a model error additionally `error`) (see data flow, step 7) | JSON |
| `GET /api/search?q=` | Chats whose title or messages contain all the words (without the thought process), with a text excerpt and `message_id` | JSON |
| `GET /api/sessions/<id>/export?format=md\|json` | Chat as a download; Markdown without the thought process | File |
| `GET /api/export` | Backup of all chats, documents, notes, knowledge base and settings, without API keys and password | File (JSON) |
| `GET /api/calendar` | Calendars (without passwords), CalDAV presets, linked mail accounts with a matching preset | JSON |
| `POST /api/calendar/sources` | `{source}`: create/change a CalDAV account or ICS address; CalDAV calendars are searched while doing so, an ICS address is read once | JSON |
| `DELETE /api/calendar/sources/<id>` | Remove a calendar (nothing changes on the server) | JSON |
| `GET /api/calendar/events?start=…&end=…` | Events of all shown calendars in the period (ISO with the device's offset, at most about a year), recurrences resolved; errors per calendar in `errors` | JSON |
| `POST /api/calendar/events` | `{source, calendar, event}` create an event | JSON |
| `PUT /api/calendar/events` | `{source, uid, href, etag, recurring, event}` change an event | JSON |
| `POST /api/calendar/events/delete` | `{source, uid, href, etag}` delete an event (for a recurrence the whole series) | JSON |
| `POST /api/calendar/parse` | `{text, now, model}`: the model reads an event from text, the response fills the form | JSON |
| `POST /api/assistant/intent` | `{text}`: is the chat message a request to prepare an event or an e-mail? Response `{action: "event"\|"mail"\|""}`; rules only (`intent.action`), no model call, INFO log "Assistant request check (chat)" | JSON |
| `POST /api/assistant/mail` | `{text, account, model}`: the model writes a new e-mail from a chat request (`mail.draft_messages`, `mail.parse_draft`); response `{to, to_name, subject, body, account}` (`account` given or the first linked one; `to` only a real address, taken from the request first). 400 "Add a mail account first" without an account. Nothing is sent or stored | JSON |
| `GET /api/profiles` | All profiles (without PINs: `has_pin`), `current` and `need_choice`; also works before the profile is chosen | JSON |
| `POST /api/profiles/select`, `POST /api/profiles/leave` | `{id, pin}` sets the cookie `sunak_profile`, wrong PIN: 403 after one second; `leave` deletes it | JSON |
| `POST /api/profiles`, `PATCH`/`DELETE /api/profiles/<id>` | Create a profile `{name, emoji, pin, admin}` (admin), change it (admin or one's own, without admin rights), delete it with all its data (admin; not the main profile and not one's own) | JSON |
| `POST /api/mcp/test` | `{server}` (as in the settings form, not yet saved) start once; response `{tools: [{name, description}]}` | JSON |
| `POST /api/tools` | Like `/api/chat`, but the model works with the tools of the switched-on MCP servers (see Tools (MCP)); from other devices only with a password | NDJSON `start` (with `run`), `think`, `text`, `step`, `confirm`, `step_done`, `notice`, `ping`, `done` (`stopped`)/`error` |
| `POST /api/tools/confirm` | Answer to `confirm`: `{run, id, decision}` with `allow`, `always` (for this chat) or `deny` | JSON |
| `POST /api/tools/cancel` | `{run}` stops the answer with tools, a running tool call is aborted | JSON |
| `POST /api/tools/revoke` | `{session_id}` forgets "allow in this chat" | JSON |
| `POST /api/chat` | Produce an answer; `use_kb` and `use_web` switch the knowledge base and web search on or off for the chat, `persona` chooses a persona, `images` and `image_refs` attach pictures | NDJSON `start`, `sources` (only with the knowledge base), `status` and `web` (only with web search), `think`, `text`, `done`/`error` |
| `POST /api/compare` | One prompt to 2 to 4 models | NDJSON with model index `i` |
| `POST /api/research` | Web research with a report | NDJSON `status`, `sources`, `text`, `done`/`error` |
| `GET`/`POST /api/documents`, `GET`/`PUT`/`DELETE /api/documents/<id>` | Documents | JSON |
| `POST /api/documents/ai` | AI editing of a document or a selection | NDJSON `text` |
| `GET /api/mail/accounts` | Accounts without password (`has_password`), plus `presets` (servers of known providers) | JSON |
| `POST /api/mail/accounts` | Create an account `{account}` or change it (same `id`); an empty password keeps the stored one | JSON |
| `DELETE /api/mail/accounts/<id>` | Remove an account from Sunak (nothing changes on the mail server) | JSON |
| `POST /api/mail/test` | Check IMAP and SMTP with the data from the form: `{imap, smtp}`, empty means "works", otherwise the error message | JSON |
| `GET /api/mail/<id>/folders` | Folders with `role` (`inbox`, `drafts`, `sent`, `archive`, `junk`, `trash`, …) | JSON |
| `GET /api/mail/<id>/messages?folder=&q=&unread=1&before=` | Newest 40 mails (headers), `before` (UID) pages to older ones | JSON |
| `GET /api/mail/<id>/message?folder=&uid=` | One mail as text with an attachment list | JSON |
| `GET /api/mail/<id>/attachment?folder=&uid=&i=` | Download an attachment (always as a download) | File |
| `POST /api/mail/<id>/send` | Send `{to, cc, bcc, subject, body, in_reply_to, references, attachments: [{name, data}], forward: {folder, uid, attachments: [index]}}`; `data` is Base64 | JSON (`saved_to`, `warning`) |
| `POST /api/mail/<id>/draft` | Same format, lands in the Drafts folder | JSON (`folder`) |
| `POST /api/mail/<id>/move` | `{folder, uids, target}`: mails to another folder | JSON (`folder`) |
| `POST /api/mail/<id>/delete` | `{folder, uids, permanent}`: to the trash; permanent only with `permanent: true` in the trash or without a trash | JSON (`permanent`, `folder`) |
| `GET /api/mail/new` | Per account `{id, email, unseen, uidvalidity, latest (up to 5 newest unread), error}` from the inbox, read-only | JSON |
| `POST /api/mail/ai` | `{task: summarize\|reply\|overview, text, instruction, account, model}` | NDJSON `think`, `text`, `done`/`error` |
| `GET`/`POST /api/notes`, `PATCH`/`DELETE /api/notes/<id>` | Notes and memory | JSON |
| `GET /api/knowledge` | Files of the knowledge base, total size, whether FTS5 is available | JSON |
| `POST /api/knowledge` | Add a file: `{name, data}` with `data` as Base64; the same name replaces the old file | JSON |
| `GET`/`DELETE /api/knowledge/<id>` | File with extracted text, remove a file | JSON |
| `GET /api/knowledge/search?q=` | Full-text search with a text excerpt | JSON |
| `GET`/`POST /api/lan` | Phone access: state, address and QR code; `{enabled}` switches it (only with a password) | JSON |
| `GET /api/images/<name>` | A picture attached to a message | Image |
| `POST /api/extract` | Text of a file for a chat attachment (paperclip), same format as above | JSON |
| `POST /api/imagine/intent` | `{text, model, quick, where}` (`where`: `chat` or `research`, only for the log): is the chat message a picture request? Response `{image, subject, via}`; `via` is `rules` or `model` (for `maybe`/`no` the chat model is asked when images are set up and `ai_image_detect` is on; `quick` never asks it) | JSON |
| `POST /api/imagine` | `{session_id, prompt, negative, aspect (square\|portrait\|landscape\|auto), seed, improve, model, fallback}`: generate a picture with the configured program; description and picture are stored as messages. With `improve`, `prompt` is the user's request in their own words: the chat model `model` turns it into a prompt for the image model (`imagegen.improve_messages`/`clean_prompt`; on error or without a model `fallback` applies, the plain description), `aspect: auto` reads the format from the text (`aspect_from_text`). Closing the connection cancels in the program | NDJSON `start`, `status` (`t`), `queued` (`position`, 0 = its turn), `prompt` (the prompt for the image model), `progress` (`p` 0 to 1 or `null`), `done` (`image`, `info`)/`error` |
| `GET /api/imagegen/local` | Own image program (`engine.installed`, `tag`, `kind`) and image models with `installed`, `partial`, `downloading`, `fits`, `gpu`, license | JSON |
| `GET /api/imagegen/engine` | Matching stable-diffusion.cpp files of the newest version, best first (admin) | JSON |
| `POST /api/imagegen/engine/install` | `{name}` from this list: download and unpack (admin); an address from the browser is never accepted | NDJSON `progress` (`completed`, `total`), `done`/`error` |
| `POST /api/imagegen/engine/remove` | Delete the image program, models stay (admin) | JSON |
| `POST /api/imagegen/models/pull` | `{id}` from the catalog or `{repo, path}` from the search: download, cancel = pause (admin) | NDJSON as above |
| `POST /api/imagegen/models/delete` | `{id}` delete an image model (admin) | JSON |
| `GET /api/models/search?q=&kind=chat\|image` | Ollama library and Hugging Face; unreachable sites are listed in `unreachable` | JSON |
| `GET /api/models/files?repo=&kind=` | Files of a Hugging Face repository with size, quantization, Ollama name (`hf.co/<repo>:<quant>`), license, `gated` | JSON |
| `POST /api/imagegen/test` | `{type, url}` from the form: models of the program (admin profiles only) | JSON |
| `POST /api/transcribe` | Voice input: `{audio}` (WAV as Base64, optional `language`) to the Whisper server, response `{text}` | JSON |

Errors always come as `{"error": "…"}` with an HTTP status of 4xx. Errors that occur only during a stream come as an event `{"type": "error"}`.

## Backends

A provider is an entry `{id, name, type, base_url, api_key}`, stored in the setting `providers`.

- **`ollama`** uses `/api/tags`, `/api/chat` (streaming, thought process in the field `thinking`), `/api/pull` and `/api/delete`.
- **`anthropic`** (Claude) uses the Anthropic API directly over HTTP, without an SDK, so that Sunak stays free of dependencies. `GET /v1/models` (paged) delivers the models; if the endpoint is unreachable, Sunak takes a built-in list (`CLAUDE_FALLBACK_MODELS`), while a rejected key is shown as an error. Chats run through `POST /v1/messages` with `stream: true`, and the server-sent events are split into text (`text_delta`) and thought process (`thinking_delta`). In this:
  - The system prompt is a field of its own, `system`; consecutive messages of the same role are merged.
  - Models with adaptive thinking (Opus/Sonnet from 4.6, Fable) get `thinking: {type: "adaptive", display: "summarized"}` so that the summarized thought process is visible. Haiku and older models get no `thinking`.
  - `temperature` is not sent, because current Claude models reject it. `max_tokens` depends on the model (`claude_max_tokens`).
  - For Claude Opus 5.5, Opus 5, Sonnet 5.5 and Fable 5.1 on `api.anthropic.com`, Sunak sets `fallbacks: "default"` (beta header `server-side-fallback-2026-07-01`). If a safety filter rejects a request, the API then answers it with a replacement model. A final refusal (`stop_reason: "refusal"`) appears as an error message.
  - The key goes to the API as `x-api-key` with `anthropic-version: 2023-06-01`.
- **`openai`** uses `/models` and `/chat/completions` with server-sent events. Thought processes come from `reasoning_content` or `reasoning`. This works with OpenAI, OpenRouter, Groq, LM Studio, llama.cpp and vLLM.

Local addresses (localhost, private IPs, `*.local`, `host.docker.internal`) are always contacted directly, never through a system proxy.

Model IDs have the form `provider::model`, for example `ollama::qwen3:4b` or `claude::claude-opus-5-5`.

**API keys** live only in the local database. `GET /api/settings` returns only `has_key` instead of the key. If the browser sends an empty key field when saving, the stored key is kept. Keys appear neither in error messages nor in logs. If `ANTHROPIC_API_KEY` is set, Claude is entered as a provider automatically on the first start.

## Native Ollama integration

The "Models" page and the setup on the first start use `sunak/ollama.py`:

- **Status**: `ollama.status` queries `/api/version` and `/api/tags` of the first provider of type `ollama`. If Ollama does not answer, Sunak looks for the program file: `PATH`, Homebrew, `/Applications/Ollama.app`, `%LOCALAPPDATA%\Programs\Ollama`.
- **Starting**: If Ollama is installed but stopped, `ollama.start` starts it in the background. On macOS this happens through the app, otherwise through `ollama serve` as a detached process. Then Sunak waits up to 15 seconds for an answer. This works only when the provider points to `localhost`.
- **Installing**: On Windows Sunak uses `winget`, on macOS Homebrew; neither needs an admin password. The output is streamed live. On Linux the official installer needs `sudo`, so Sunak shows the command to copy. Without Homebrew there is a download link.
- **Catalog**: `CATALOG` is a curated list with name, approximate size, tags and description. `fits()` marks models that fit into the memory. The rule of thumb is: size × 1.3 + 2 GB.
- **Download**: `POST /api/models/pull` streams `/api/pull` from Ollama and sums the progress of all layers. If the browser aborts the request ("Cancel"), the server closes the connection to Ollama and the download stops. Parts that were already loaded are kept, a new start resumes there.
- **Frontend**: Running downloads live in `state.pulls` and continue when you switch pages. Every element with `data-slot`/`data-pull` shows the same progress, for example catalog card, download list and setup card in the chat.

## GPU

Sunak does not compute anything itself; Ollama uses the GPU on its own (CUDA, ROCm, Metal). Sunak makes sure you can see whether that works, and adjusts the recommendations.

- **Detection** (`sunak/gpu.py`): NVIDIA via `nvidia-smi` (name, VRAM; if the driver is missing, Linux still finds the card via `/sys/class/drm` and Sunak recommends the driver), AMD and Intel on Linux via `/sys/class/drm` (`mem_info_vram_total`), on Windows via the registry (`HardwareInformation.qwMemorySize` of the graphics adapters, without extra programs), Apple Silicon via `platform.machine()`. An NVIDIA or AMD card with a driver and at least 3 GB of VRAM, or Apple Silicon (shared memory), counts as usable for Ollama. Intel graphics and small integrated AMD GPUs do not count. Detection runs once at startup in the background (`App.gpu`); any error simply means "no GPU".
- **Checking usage:** `GET /api/ollama` additionally queries `/api/ps`. For every loaded model it contains `size_vram`, from which the GPU share is derived. If not a single byte is on the GPU although a usable GPU is present, `gpu.cpu_warning` delivers a help text per vendor.
- **Local only:** The GPU of this computer counts only when the Ollama provider points to `localhost`. With Docker, Ollama runs in a container of its own; the GPU Compose files therefore set `SUNAK_GPU=nvidia|amd` in the Sunak container so that the warning works there too.
- **Recommendations:** The catalog marks models with `gpu` that fit completely into the VRAM (size × 1.2 + 1 GB); on Apple Silicon the RAM rule applies. `recommend()` takes a larger starter model if it fits completely into the VRAM, but never a smaller one than by RAM.
- **Installer and command line:** `sunak gpu` prints the result as text; `install.sh` and `install.ps1` show it before the Ollama installation. The GPU part (CUDA or ROCm libraries) is brought along by the official Ollama installer itself.

## Tools (MCP)

`sunak/mcp.py` is an MCP client (protocol version `2025-06-18`) using only the standard library. Of MCP, Sunak uses only tools (`tools/list`, `tools/call`).

- **Server types:** `stdio`: Sunak starts the command (`shutil.which`, so also `npx.cmd` on Windows) in the home folder with the stored environment variables and speaks JSON-RPC line by line over stdin/stdout; lines that are not JSON are skipped, `ping` and `roots/list` of the server are answered, the error output (last 2000 characters) appears in messages. `http`: Streamable HTTP, JSON-RPC via POST to an address, answer as JSON or server-sent events, `Mcp-Session-Id` and `MCP-Protocol-Version` are sent along, optionally a bearer token; `DELETE` on shutdown.
- **Lifetime:** `App.mcp` (`mcp.Manager`) starts the switched-on servers when a chat with tools switched on needs them for the first time (in parallel, at most 60 s, because `npx -y`/`uvx` download on the first run), and keeps them running. Changed or removed servers are ended when saving, crashed ones are restarted at the next chat, all of them when Sunak ends.
- **In the chat:** `POST /api/tools` (`sunak/toolrun.py`). `toolrun.ToolRun` offers the tools to the model in the backend's format; the name is `<server>__<tool>` (at most 64 characters from `[a-zA-Z0-9_-]`, longer ones with a hash), the description and the `inputSchema` come from the server. Every call needs approval (`confirm` with `kind: "tool:<name>"`, `server`, `mcp_tool` and the input as JSON); "allow in this chat" applies per tool. Required arguments are checked beforehand, `isError` and connection errors go back to the model as errors, Stop sends `notifications/cancelled`. Pictures and audio from results are passed on only as placeholders.
- **Loop:** The model answers, calls tools, gets the results and continues until it calls no more tools, at most `MAX_STEPS` (30) rounds per answer. Results go to the model with at most 30,000 characters. Before a call the server sends `confirm` and waits (a `ping` every 15 s, after 30 minutes it counts as "Deny"); `always` lives only in memory (`toolrun.Registry`) until Sunak restarts or "Ask again" is clicked. Denied steps go back to the model as errors.
- **Tool calling per backend:** Claude via `tools` of the Messages API; thinking blocks (with signature), text and `tool_use` go back unchanged, results as `tool_result`. On `api.anthropic.com` `eager_input_streaming` is on; the arguments are parsed strictly as JSON and checked only after they have been received completely. Ollama via `tools` in `/api/chat`, results as role `tool` with `tool_name`. OpenAI-compatible via `tools`, pieces of `tool_calls` are assembled per `index`, results with `tool_call_id`.
- **Text protocol:** If Ollama reports "does not support tools" (or an OpenAI-compatible API rejects the parameter `tools` with an error), Sunak switches to a text protocol for this answer and shows a hint. The model then writes a block ` ```tool {"tool": …, "args": …}`. Sunak reads it with `json.JSONDecoder.raw_decode`, stops generation after the first complete block (so that the model does not invent a result), does not show the block as text and sends the result as a message `[Result of …]`.
- **Storing:** The answer is stored with its parts: `messages.meta.tools = {parts}`, where `parts` contains text sections and steps (tool, title, status `done`/`error`/`denied`/`stopped`, shortened output) in order. `content` contains only the text; later requests therefore see the answers but not the old tool results. Chats from version 0.12 and earlier with `meta.agent` (the removed agent mode) stay readable: `app.js` still shows their steps. Old `agent_*` settings in the database are ignored (`App.settings` reads only known keys).
- **Settings:** `settings.mcp_servers` = `[{id, name, type, enabled, command, env | url, token}]`, validated by `mcp.clean`. The browser gets only `mcp.public`: instead of the values `env_keys` or `has_token`. If it sends a server back without `env`/`token`, the stored ones are kept, but only with the same command or address (otherwise they could go to another program).
- **Access:** Servers of type `stdio` run programs with the user's permissions. Therefore changing `mcp_servers`, `/api/mcp/test`, chats with MCP and approvals from other devices (or through a reverse proxy) require a password to be set.
- **Interface:** The plug button next to the input box appears as soon as a server is switched on; the switch is stored in `localStorage` (`sunak-mcp`). Settings → Tools (MCP) with a card per server, "Test" and presets (files, reading web pages, time, memory). Pictures in the chat are rejected for chats with tools.

## Web search in the chat

A switch per chat like the knowledge base (`sessions.use_web`, `use_web` in the request). If it is on, `Handler.chat` calls `web_search` after the `start` event:

1. Search query: for the first question the text itself (without attached files), for follow-up questions the model writes a short search query from the last five messages (`temperature` 0), so that "and in Hamburg?" works.
2. `research.gather` searches (DuckDuckGo or `SEARXNG_URL`) and reads the hits in parallel; up to four pages with more than 200 characters remain, cut to 3000 characters each.
3. `research.web_context` puts them, numbered and with a date, into the system prompt, with the instruction to cite sources as `[1]` and to treat text in them as third-party data, not as an instruction.
4. The browser gets `status` events ("Searching the web: …") and `web` with the query and sources; both are stored in `messages.meta.web`.

If the search fails or finds nothing readable, the model answers without the web and the browser sees the reason as a status.

## Deep Research

1. The model proposes up to three search queries.
2. `research.clean_queries` turns the model's answer into search queries: `<think>` blocks (also an incomplete one), numbering, bullets, quotation marks, Markdown, "Query:" labels, chatter sentences ("Okay, let's…", "Here are…") and overly long lines are dropped; if nothing is left (some models, for example Qwen, answer only with thoughts) or the call fails, the question itself is the query. If the model's queries find nothing, the question is searched last. The log gives only the number and length, never the text ("Research: n search queries").
3. `research.search` searches via DuckDuckGo (no key), then DuckDuckGo Lite, then Bing (`parse_ddg`, `parse_ddg_lite`, `parse_bing`; Bing redirects are decoded from `u=a1…`). A robot-check page counts as an error (`PermissionError`), not as "no hits". If `SEARXNG_URL` is set, only SearXNG is used. If no search engine is usable, `search` raises `SearchError` with the reason per search engine; if they merely return nothing, the result is empty. The message distinguishes "web search does not work" (with reasons and a hint about `SEARXNG_URL`) from "found nothing". Web search in the chat uses the same cleanup for its search query.
4. Up to five pages are loaded and converted to text, at most 6000 characters each.
5. The model writes a Markdown report with source references like `[1]`.

## Mail

`sunak/mail.py` uses only `imaplib`, `smtplib` and `email`. Every request opens a connection of its own and closes it again; there is no background service.

- **Accounts** live in the setting `mail_accounts`: `{id, email, name, username, password, imap_host, imap_port, imap_security, smtp_host, smtp_port, smtp_security, save_sent}`, `*_security` is `ssl`, `starttls` or `none`. `none` and accepting self-signed certificates exist only for `localhost`/loopback (for example Proton Mail Bridge). `mail.clean_account` validates everything; an empty password adopts the stored one only with the same user name and the same servers, so that it never goes to another server. `PRESETS` contains the servers of known providers with their domains (the frontend picks the preset by the address) and a hint text about the app password.
- **Passwords** never leave the server: `mail.public` removes them, `/api/export` does too. Error messages pass through `_safe`, which replaces a password to be safe. Non-ASCII passwords go via `AUTHENTICATE PLAIN` (IMAP) or a custom `AUTH PLAIN` (SMTP) in UTF-8, because `LOGIN` and `smtplib.login` only handle ASCII.
- **Read-only:** Folders are opened with `EXAMINE` (`select(readonly=True)`) and mails are fetched with `BODY.PEEK`, so `\Seen` stays unchanged. The list fetches only `FROM TO SUBJECT DATE`, flags and size; search via `UID SEARCH TEXT` (every word must occur), text with umlauts as a UTF-8 literal with `CHARSET UTF-8`.
- **Reading a mail:** at most 10 MB per mail, text preferably from `text/plain`, otherwise HTML is converted to text with `research.html_to_text` (scripts are dropped, nothing is loaded). Folder names come in IMAP's modified UTF-7 and are made readable with `utf7_decode`. A folder's role comes from the special-use flags (RFC 6154), otherwise from the name ("Gesendet", "Entwürfe", …).
- **Writing:** `build_message` builds an `EmailMessage` (addresses checked, line breaks removed from headers, `In-Reply-To`/`References` for replies). `attachments` collects the files: uploaded ones (Base64, name cleaned, MIME type from the extension) and, when forwarding, the chosen attachments of the original, which the server fetches completely (up to 48 MB instead of the 10 MB for display) from the mailbox with `_original_attachments`. Together at most `MAX_ATTACH` (17 MB). `send` sends via SMTP and, with `save_sent`, puts a copy into the Sent folder with `APPEND` (Gmail and Outlook do that themselves, so it is off there). If only the copy fails, the mail has been sent anyway and there is a warning. `save_draft` puts the mail with `\Draft` into the Drafts folder.
- **Moving and deleting:** the only writing IMAP commands besides `APPEND`. `_move` opens the folder with `SELECT` (writable) and uses `UID MOVE` (RFC 6851) if the server can do it; otherwise `UID COPY`, set `\Deleted` and `UID EXPUNGE` (UIDPLUS), without UIDPLUS a plain `EXPUNGE` like other mail programs. `delete` moves to the folder with the role `trash`; permanently (`\Deleted` + expunge) only from the trash or for accounts without one. Target and source folders must be in the folder list. Gmail maps labels to folders: `MOVE` swaps the label, the trash is `[Gmail]/Trash` with `\Trash`.
- **New mail:** `check_new` opens the inbox read-only, searches `UNSEEN` and returns the count, `UIDVALIDITY` and the five newest. The browser queries `/api/mail/new` every 2 minutes (setting `mail_notify`, per profile), remembers per account `UIDVALIDITY` and the highest reported UID in `localStorage` (`sunak-mail-seen`); the first query only sets this boundary. Newer UIDs produce a notice with "Open" and, if allowed and the page is in the background, a `Notification`. The number on the Mail button is the sum of unread mails.
- **Self-test:** `sunak/mailtest.py` reads the accounts from the databases of all profiles (read-only) or asks for address and app password with `getpass` (`--new`, servers from `PRESETS`). Every test mail has `sunak-selftest-<random>` in the subject; `mail.find` searches via `UID SEARCH SUBJECT` and checks every hit itself, because Gmail's search compares words fuzzily. Cleanup: all folders except the trash into the trash, delete permanently there (several times, because Gmail is delayed). Output ✓/✗/! per step, exit code 0 only without ✗.
- **AI:** `ai_messages` builds the prompts for `summarize`, `reply` and `overview`. The mail is in `<email>` tags, and the system prompt says that its content is data and not instructions. Memory notes are passed along (for example the user's own name for the greeting). The answer is streamed only into the form. "Ask in chat" attaches the mail in the browser as a file attachment named "E-mail: subject" (translated in the German interface) to a new chat, exactly like a file via the paperclip.
- **Frontend:** Section "Mail" in `app.js`: account and folder selection, list with "Load older", reading view with "Move to…" and Delete (confirmation, in the trash "permanently?"), form for a new mail, reply, forward, attachments as chips (`renderComposeFiles`; own files as Base64, forwarded ones only as an index). Sending asks first. New mail: `checkNewMail`. Setup is in Settings → Mail accounts (`editMailAccount`).

## Knowledge base

Uploaded files take the path `extract.extract_text` → `knowledge.chunk` → `DB.kb_add`.

- **Text extraction** with only the standard library. Word, OpenDocument and PowerPoint are ZIP archives with XML and are read with `zipfile` and `ElementTree`. For PDF there is a small reader of its own: it finds all objects (also in object streams of PDF 1.5+), unpacks Flate, ASCII85 and ASCIIHex streams, follows the page tree with inherited resources and translates characters via the font's `ToUnicode` CMap, otherwise via WinAnsi or MacRoman. Spaces and line breaks result from the text positions. Form XObjects are read along.
- **Limits:** Scanned PDFs without a text layer (that would need text recognition) and encrypted PDFs give an understandable error message. For fonts without `ToUnicode` that contain only glyph numbers, the text stays empty. Multi-column layouts are read in the order of the content stream.
- **Sections** of about 1000 characters at paragraph, line or sentence boundaries.
- **Search:** SQLite FTS5 (`kb_fts`, rowid = `kb_chunks.id`, umlauts and accents are ignored in comparison) with bm25 ranking. The search words come from the last two questions without stop words (German and English), words of 4 letters or more also as a prefix, so that "Handbuch" also finds "Handbuchs". If FTS5 is missing in the SQLite build, `knowledge._scan` calculates a simple TF-IDF in Python.
- **Prompt:** If the whole knowledge base is at most 8000 characters, the model gets everything (then questions like "summarize this" work too). Otherwise it gets up to 6 matching sections with at most 7000 characters. The sections are in the system prompt with file names, and the model is told to name the file in square brackets.
- **Sources:** The files used are sent as a `sources` event and stored in `messages.meta`, so that they also appear under the answer later.

## Start, autostart and desktop icon

- **Only one Sunak:** Before starting, `__main__` asks ports 7000 to 7009 for a running Sunak. If one answers, only the browser is opened. That is why the desktop icon can be clicked any number of times.
- **Stopping:** `sunak stop` sends `POST /api/shutdown` to the running Sunak. Whoever started Sunak through the icon without a terminal stops it in Settings with ⏻ Stop Sunak.
- **Autostart** (`sunak autostart on`) starts Sunak at login with `--no-browser` in the background:

| System | File |
|---|---|
| Linux | `~/.config/autostart/sunak.desktop` (XDG autostart, works in GNOME, KDE, Xfce etc.) |
| macOS | `~/Library/LaunchAgents/dev.sunak.plist` (LaunchAgent with `RunAtLoad`, log in `~/.sunak/sunak.log`) |
| Windows | `Sunak.vbs` in the Startup folder; starts `pythonw` without a console window |

- **Desktop icon** (`sunak shortcut`): Linux puts `sunak.desktop` in the app menu and on the desktop (marked as trusted on GNOME), macOS a small `Sunak.app` in `~/Applications` with a link on the desktop, Windows `Sunak.lnk` on the desktop and in the Start menu, which starts a hidden `Sunak.vbs`.
- All entries call the current Python interpreter with `-m sunak` and set `PYTHONPATH` to the installation folder, so they also work without a `sunak` command in the `PATH`.
- `sunak uninstall [--yes] [--purge]` (`sunak/uninstall.py`): stops a running Sunak, removes autostart, icons (only its own: `.desktop` files with `-m sunak`, the `Sunak.app` symlink, `Sunak.lnk`), the launcher (only with the marker "Sunak launcher"), `app`, `source` or on Windows `%LOCALAPPDATA%\sunak` and the PATH entry (the line with `# sunak PATH` in `.bashrc`, `.bash_profile`, `.zshrc`, `.profile`; on Windows the entry in the user `Path` of the registry, the type is preserved). Docker Compose projects with a service `sunak` are found via their labels; the Sunak container (with the built image) only after confirmation or with `--yes`, the Ollama container (with image) only after its own confirmation or with `--with-ollama`. Data (`SUNAK_DATA` or `~/.sunak`, with Docker `data/` in the project folder without `data/ollama`) is deleted only by `--purge` or an explicit `y`. Ollama itself (`ollama_install` detects the route: Inno uninstaller `unins000.exe` or winget on Windows, Homebrew cask, formula or app on macOS, the official `install.sh` with a systemd service, Snap or distribution package on Linux) is removed only by a `y` or `--with-ollama`; failures of harmless steps (stopping the service, deleting the user) do not count. Models (`OLLAMA_MODELS` or `~/.ollama/models`, `/usr/share/ollama/.ollama/models`, `data/ollama` with Docker) are deleted only by a `y` or `--with-models`, not by `--purge` and not by `--with-ollama`. Without a terminal the default applies to every question, that is, delete nothing. It never deletes the home folder, folders above it or drive roots. The Windows launcher calls `uninstall` in a block with `exit /b`, because `cmd` would otherwise keep reading the deleted `sunak.cmd`.
- `sunak update` fetches the new code: if the installation came from a Git clone, the installer remembers its path (`~/.sunak/source`, Windows `%LOCALAPPDATA%\sunak\source.txt`), and the update does `git pull` there and reinstalls. For the public repository no credentials are needed (`git fetch` and `pull` run anonymously over https, `GIT_TERMINAL_PROMPT=0` prevents prompts); a private fork works with the clone's credentials. Otherwise the current installer is downloaded. `sunak update` first shows the changes (`sunak changelog --confirm`, see "Changelog" below) and asks; `--yes` and a missing terminal skip the question, and No (exit code 3 of `changelog`) ends the launcher without error and without changing anything. The update shows the old and the new version and stops a running Sunak, so that the next start uses the new version.

## Update notice

- **Check** (`sunak/updates.py`, `App.check_updates`): at startup and then at most every 6 hours (after a failure again after 30 minutes) a `git fetch` runs in the background in the clone Sunak comes from: the app folder itself if it is a Git clone, otherwise the clone remembered by the installer (`~/.sunak/source`, Windows `source.txt`). The commits between the installed version and the upstream branch are counted (`git rev-list --count <installed>..@{u}`). The installer writes the installed version to `.commit` in the app folder, so a clone that has already been pulled but not yet reinstalled is noticed too.
- **Failing quietly:** without git, without a network, without a clone, without an upstream branch or on password prompts (`GIT_TERMINAL_PROMPT=0`, no terminal, on Windows `GCM_INTERACTIVE=never`) there is simply no notice.
- **Interface:** `GET /api/update` on load, after 20 seconds and then hourly. If there are new commits, "Update available" appears at the top of the sidebar with the button **Update**; it opens a dialog with the changelog (Install update / Cancel), and only there anything is installed. It can be switched off in Settings → Updates (`check_updates`); the button "Check for updates now" there calls `POST /api/update/check` and names the reason on a failure.
- **Update button:** `POST /api/update` starts `python -m sunak.updates` as an independent process and ends the server. The helper process waits until the old server is gone, runs `git pull --ff-only` (the app folder is a clone) or the installed command `sunak update`, writes the result to `update-result.json` in the data folder, logs to `update.log` and restarts Sunak with the same host, port and data folder. The page recognizes the restart by the changed `instance` in `/api/status`, reloads and shows the result once. Nothing is ever installed without a click.

- **Changelog** (`sunak/changelog.py`, `CHANGELOG.md` in the main folder): one section per version, newest first, `## [a.b.c] – YYYY-MM-DD` plus Markdown points. `updates.inspect` reads the file with `git show @{u}:CHANGELOG.md` from the state after the `fetch` (the working copy is not touched) and returns the sections with a version greater than the running one and at most the version on the remote (`changelog` in `/api/update` and `/api/update/check`; cached together with the update hint). The page renders `body` with its own safe Markdown renderer (`md`), in the dialog of the Update button and under "Check for updates now" in Settings. An empty list (file missing, broken, or no version in between) shows "No changelog available" and the update still works. In the terminal: `sunak changelog` (look) and `sunak changelog --confirm [--yes]` (asks "Install the update now? [y/N]"; no question without a terminal or with `--yes`; exit code 3 = declined), which the launcher (`install.sh`, `sunak.cmd`) runs before the update. Rule for developers: every new version gets a section in `CHANGELOG.md` in the same commit (a test checks that the top section is the version in `sunak/__init__.py`).

## Data storage

All data lives in one SQLite file: `~/.sunak/sunak.db`; the folder can be changed via `SUNAK_DATA`.

| Table | Contents |
|---|---|
| `sessions` | Chats: title, model, own system prompt, `use_kb` (knowledge base on/off), `use_web` (web search on/off), `persona` (id) |
| `messages` | Messages of the chats (deleted with the chat); `meta` (JSON) contains for example the sources or the names of attached pictures (files in `images/` next to the database) |
| `kb_files`, `kb_chunks`, `kb_fts` | Knowledge base: files, their text sections and the full-text index |
| `documents` | Markdown documents |
| `notes` | Notes; `is_memory = 1` means "in memory", `source` is the chat ID if Sunak created them itself |
| `usage` | One record per model request (see `GET /api/usage`), in the database of the respective profile; no deletion, the sum is formed per query via SQL |
| `settings` | Key-value pairs as JSON: `prefs` (including theme, language, image generation), `providers`, `personas` (if the entry is missing, `DEFAULT_PERSONAS` apply), `mail_accounts`, `calendars`, `mcp_servers`, `report_token` (GitHub token for error reports, main database only), `profiles` (main database only), `lan_access`, `password_hash`, `secret` |
| `calendar_events` | Sunak's own calendar: `uid`, iCalendar text, modification time |

Every further profile has its own file with the same tables under `profiles/<id>/` (see Profiles).

Columns that were added later are created by `DB.__init__` at startup (`MIGRATIONS`), so older databases keep working. The uploaded original files are not kept, only their text.

Passwords are stored with PBKDF2-SHA256 and a salt. The login cookie is an HMAC of the installation's secret and the password hash. If the password is changed, all sessions are therefore logged out.

## Profiles

A profile is a database of its own: the main profile (`default`) uses `~/.sunak/sunak.db`, every further one `~/.sunak/profiles/<id>/sunak.db` with its own `images/` folder. The list of profiles (name, emoji, `admin`, PIN as a PBKDF2 hash) is in the setting `profiles` of the main database. At most `MAX_PROFILES` (20) profiles exist.

- `Handler.route` determines the profile before every endpoint: from the cookie `sunak_profile=<id>.<hmac>` (HMAC of the installation's secret, the id and the PIN hash; a changed PIN therefore logs other devices out of the profile) or, if there is only one profile without a PIN, that one. Otherwise all endpoints except profile choice, login and status answer with 409 "Choose a profile", and the page then shows the choice.
- `App.view(id)` returns a `ProfileView`: the same `App`, but with the profile's `db` and `user_dir`. Everything else (providers, MCP manager, running answers with tools, phone access) it forwards to the `App`. The endpoints notice nothing; they use `self.app.db` as before.
- Settings: `GLOBAL_PREFS` (update check, voice input) as well as `providers`, `mcp_servers` and the password apply to the installation and live in the main database; theme, language, system prompt, personas, mail accounts and calendars per profile.
- Admin rights: `ADMIN_ONLY` lists the endpoints that only admin profiles may call (create and delete profiles, download and delete models, Ollama, updates, error reports, phone access, MCP tools and tests, image program), `put_settings` rejects global settings from other profiles with 403. The page hides these areas for them (`body.not-admin .admin-only`).
- Limits: The PIN separates the profiles in the app. Whoever is logged in on the computer can read the files of all profiles; an admin profile with MCP tools can too. The password (login) applies to the whole installation.

## Model search

The Models page filters Sunak's catalogs (Ollama models with tags `chat`, `vision`, `coding`, `reasoning`; image models) instantly in the browser by text, type, size and "fits your computer". "Search online" calls `/api/models/search`: `modelsearch.ollama_search` reads the search page of ollama.com (there is no official search API; the parser is tolerant and returns nothing when in doubt), `hf_search` queries `GET /api/models?search=…&filter=gguf` or `pipeline_tag=text-to-image` at Hugging Face. Both run in parallel with a short timeout; whatever does not answer is simply missing. `hf_files` reads model info (license, `gated`) and the file list (`/tree/main`); Ollama loads GGUF files directly as `hf.co/<repo>:<quant>`, `sdcpp` loads image checkpoints.

## Image generation

Two routes: Sunak's own image program (`sdcpp.py`, `image_gen = local`) or a Stable Diffusion program that the user runs themselves (`imagegen.py`). Settings (admin profiles only): `image_gen` (`off`, `local`, `automatic1111`, `comfyui`), `image_gen_url` (empty = `DEFAULT_URLS`), `image_gen_model`, `image_gen_size` (512, 768 or 1024 as the side of a square picture; portrait and landscape 2:3 and 3:2 with about the same area, multiples of 64) and `image_gen_steps`.

- **Own program (stable-diffusion.cpp):** `GET /repos/leejet/stable-diffusion.cpp/releases/latest` lists the ready-made programs; `rank_assets` chooses by system, processor and graphics card (NVIDIA: CUDA with the CUDA runtime as a second archive, other cards: Vulkan, Mac: Metal, otherwise the AVX2 version). The user sees the list and clicks; the server accepts only names from this list. The ZIP is checked (no paths outside), unpacked to `<data>/imagegen/engine`, the program (`sd-cli` or `sd`) is searched for and remembered in `engine.json`. Models come from `CATALOG` (Hugging Face repository, file, role, license, recommended size, steps, CFG, sampler) or from the search (one checkpoint file, `model.json` in the model folder) into `<data>/imagegen/models/<id>/`. `download` writes into a `.part` file and resumes with `Range`; cancelling is a pause. For a picture, `generate` starts the program with `-m/--vae`, `-p`, `-n`, `-W`, `-H`, `--steps`, `--cfg-scale`, `--sampling-method`, `-s`, `-o`, reads the progress bar (`3/20`) for the display and ends the process on Stop. Picture size, steps and CFG come from the model.
- **What is missing:** `sdcpp.status` checks the program, the chosen model and downloaded models and returns `{problem, model}`: `no_engine`, `no_model`, `choose` (everything is there, but `image_gen` is still `off` or the model is missing: `model` is the one to take) or empty. `GET /api/settings` contains this as `image_status`. There is no picture button: if something is not set up, `imagineSetup` names the missing step on a picture request in the chat (for `choose` it sets everything up itself). After the program installation, model download and deletion, `refreshImageStatus` fetches the settings again. **Request in the normal chat:** Before sending (not with attachments, at most 600 characters), `pictureIntent` asks `POST /api/imagine/intent`; `sunak/intent.py` recognizes German and English with patterns (`classify`). If images are set up and `ai_image_detect` is on (default, global setting), for `yes` the rule alone decides (no extra call); for `maybe` and `no` the server asks the chat model (`App.ask_intent`: only the last message, yes/no, temperature 0, the stream is closed after the first characters), and only a YES makes a picture (`via: model`). No model, an error, more than 15 s or a backend that is currently busy (`jobqueue.snapshot`, so no waiting time and no double place arises) means: the rules decide (`via: rules`, only `yes` counts, `maybe` is a normal chat). Without images set up there is no extra call. If the server does not answer in time, the browser aborts after 30 s and the message goes out as a chat. `pictureRequest` sends it without asking back to `/api/imagine` with `improve: true`, the chat's model, `aspect: auto` and the plain description (`subject` of the intent response) as `fallback`. The chat model writes the prompt (`IMPROVE_SYSTEM`: one English sentence from keywords, 25 to 50 words, do not invent anything unrequested); the user sees it already while painting (`prompt` event) and afterwards as "Improved prompt" under the picture (`meta.imagegen.prompt`, the request is in `meta.imagegen.request`; the user message stays verbatim). No tool call by the model, so that it works with any model. If nothing is set up, a hint names the missing step (for `choose`, `imagineSetup` sets everything up itself) and the message goes to the model as a normal chat. Every check appears as INFO "Picture request check (chat/research)" in the log, also for normal messages (without their text). **Research:** The form also asks before the search (`divertPicture`); a picture request is painted in a new chat. Web search and knowledge base are switches in the normal chat and run through `sendNow`, so through the same check. Errors of the program (`generate`) name the exit code and the last error lines.
- **Events and e-mails from the chat:** Before the picture check, `sendNow` (not with attachments, at most 600 characters) asks `POST /api/assistant/intent` (`assistantIntent`); `intent.action` decides by rules, so every model works and a clear question never costs a model call. For `event` the browser calls `POST /api/calendar/parse` (the same call as "Event from text") with the device time, for `mail` `POST /api/assistant/mail`. The result becomes a local message pair in the open chat (`meta.assist`, `assistEl`; not stored on the server, a reload drops the cards). The event card has **Save** (`POST /api/calendar/events`, target from `localStorage` `sunak-cal-target` if it still exists, else Sunak's own calendar) and **Edit** (opens `editEvent`); the mail card has **Open in Mail** (`openCompose` with recipient, subject and body) and **Copy text**. The cards also have **Send as normal message** (`sendAsChat`: removes the card and sends the text with the check skipped (`send(true)`); it does nothing while the input box has text or a request runs), and the event card warns when the end lies in the past (`eventIsPast`). Nothing is saved or sent without a click, and sending still goes through the existing Send button with its confirmation. If the request cannot be read (model answer not JSON, no mail account) the card shows the error, with "Add mail account" for the latter; the message is not sent to the chat model afterwards. Usage counter: `/api/assistant/mail` counts as `mail`.
- **Automatic1111** (also Forge, SD.Next; start with `--api`): `POST /sdapi/v1/txt2img` in a thread of its own, meanwhile `GET /sdapi/v1/progress` for the bar; a chosen model goes along as `override_settings.sd_model_checkpoint`. Cancel: `POST /sdapi/v1/interrupt`.
- **ComfyUI:** the default workflow (load checkpoint, two text encoders, empty latent, KSampler with euler/normal, VAE decode, SaveImage) in API format to `POST /prompt`, then `GET /history/<id>` until the result and the picture via `GET /view`. Without a chosen model Sunak takes the first checkpoint from `/object_info/CheckpointLoaderSimple`. Cancel: remove the job from the queue and `POST /interrupt`.
- The seed is always chosen by Sunak (or passed along) so that it is shown with the picture. The picture is stored like an attached one in `images/` (`images.store`, file signature checked); the reply message has `meta.images` and `meta.imagegen` (program, model, seed, size, steps, description) and as text a short description, so that follow-up questions in the chat make sense. Generated pictures are not sent to the model as a picture (`images.attach` takes only pictures from user messages).
- If the browser aborts (Stop), the next `progress` event fails; `generate` notices that via `cancelled()` and aborts in the program.

## Phone access

`App.start_lan` opens a second `ThreadingHTTPServer` with the same `App` on the computer's network address and the same port (a different address on the same port can be bound on all three systems). The address is delivered by `lan_ip`: a UDP `connect` without a packet sent shows through which address the computer talks to the outside. The main server stays on `127.0.0.1`.

- Switching on works only with a password; if the password is removed, `save_settings` closes access immediately. Requests via the network address do not count as local (tools and stopping need a login there).
- The state lives in the setting `lan_access`; `__main__` calls `restore_lan` at startup and prints the address. If that fails (no network), the reason is in `lan_info()["error"]`.
- With `--host 0.0.0.0` Sunak is reachable on the network anyway (`fixed`); then the page shows only address and code.
- `GET /api/lan` returns the state, address and the QR code as SVG, `POST /api/lan {enabled}` switches it.
- `sunak/qr.py` generates QR codes without dependencies (byte mode, error correction M, versions 1 to 10, mask choice by penalty points). The tests compare the matrices with the library `qrcode`.
- The page has a web app manifest and the meta tags for "Add to Home Screen". Over `http://` on Wi-Fi, Android and iOS treat Sunak like a bookmark with its own icon; a full PWA installation is required by the browsers only over HTTPS or localhost.

## Frontend

`app.js` is a single file without a framework and is divided into sections: API helpers, Markdown renderer, theme, navigation, models, chats, sending, model download, Compare, Research, documents, notes, settings and start.

- The Markdown renderer first escapes all HTML and then builds only known elements. Model output can therefore not smuggle in a script.
- Streams are read line by line with `fetch` and a `ReadableStream` and redrawn once per animation frame.
- **Themes:** Every theme is a block `[data-theme="…"]` in `app.css` that sets all colors as CSS variables (`--bg`, `--panel`, `--panel-2`, `--border`, `--text`, `--muted`, `--code-bg`, `--danger`, `--ok`, `--accent`, `--accent-text`), plus, where needed, font (`--font`), corners (`--radius`) and glows (`--glow`). Shipped: `dark`, `light`, `retro`, `cyberpunk`, `ocean`, `forest`, `sunset`, `corporate`. Themes with a shape of their own (Retro, Cyberpunk, 80s Corporate) additionally have a few rules `[data-theme="…"] .class` at the end of `app.css`, such as the 3D edges (`--bevel-hi`, `--bevel-lo`) and the title bar of 80s Corporate. The list appears three times and must match: CSS, `THEMES` in `app.js` (name, subtitle) and `THEMES` in `server.py` (allowed values); `tests/test_themes.py` checks that and the contrast (text at least 7:1, muted text, accent, error and success color at least 4.5:1, text on accent buttons at least 4.5:1).
- **New theme:** Copy a block in `app.css` and change the colors, add an entry to both `THEMES` lists, run the tests.
- **Choice:** The palette button in the top bar (menu) and cards with a preview in Settings → Look. The cards carry `data-theme` themselves, so they show the real theme. A click applies immediately and is saved right away (`PUT /api/settings` with `theme` and `accent`).
- **Accent color:** An empty `accent` means "the theme's color". A custom color is set as an inline variable on `<html>`; the text color on it (black or white) is computed by `theme.js` from the brightness.
- **No flicker:** `static/theme.js` is loaded in the `<head>` of `index.html` and `login.html` before the page is painted and sets theme and accent from `localStorage`. `app.js` writes the values from the settings back there, so that every device has the most recently chosen values immediately.

## Icons

The interface uses no emojis but strokes icons of its own (`static/icons.js`, 24×24, `stroke: currentColor`), so that they take the text color in every theme and look the same everywhere. `SUNAK_ICONS` maps the name to the SVG content. In `index.html` there is `<i data-i="mail"></i>`, which `icons.js` replaces with an `<svg class="ic">` on load; in `app.js`, `icon('mail')` returns the element. Icons are decoration (`aria-hidden`): a button's name is carried by its text, `title` or `aria-label`. Classes: `solo` (button with only an icon), `after`/`before` (spacing to the text). A new icon is an entry in `SUNAK_ICONS`. `tests/test_icons.py` checks that every used icon exists and that no emojis are left in the page and code. Only user content (mails, chats) and a self-chosen profile emoji may contain emojis.

## Voice input and reading aloud

- **Microphone with Whisper (fully local):** If a Whisper server is entered under Settings → Voice, the browser records with `MediaRecorder` until the microphone is clicked again. `toWav` in `app.js` decodes the recording (WebM, Ogg or MP4, depending on the browser), converts it to 16 kHz mono with an `OfflineAudioContext` and sends it as WAV to `POST /api/transcribe`. `speech.py` passes it on as `multipart/form-data`: to whisper.cpp (`…/inference`) or to an OpenAI-compatible server (`…/v1/audio/transcriptions`, for example Speaches, faster-whisper-server, LocalAI; model name from `whisper_model`, otherwise `whisper-1`). Each of these servers reads WAV without ffmpeg. The text lands in the input box and is sent only on a click.
- **Microphone without Whisper:** the browser's speech recognition (`SpeechRecognition`). With `speech_input: "local"` (default) only on the device: Google Chrome from 139 can download a language model for this (`SpeechRecognition.available/install` with `processLocally`); other browsers do not offer this, in which case a hint explains the setup. With `"browser"` the browser may use its normal recognition; Chrome then sends the audio to Google, which the settings state this way. `"off"` hides the microphone.
- **Microphone only securely:** Browsers release the microphone only on `localhost` or over HTTPS. Through phone access (`http://` on Wi-Fi) the microphone therefore does not work; the dictation function of the phone keyboard helps there.
- **Reading aloud:** the browser's `speechSynthesis`. `speakable` removes the thought process, code blocks, Markdown, links and source numbers and splits the text into pieces under 200 characters (Chrome otherwise cuts off long texts). The voice is chosen per device (`localStorage`, because every device has different voices); "Automatic" takes a voice that runs on the device (`localService`), in the interface's language. Online voices are marked in the list.

## Languages

The source code is English. Every further language is a file `static/lang-<code>.js` that maps the English texts to their translation (`SUNAK_LANGS.de = { name: 'Deutsch', strings: {…} }`); `{name}` marks a changing part.

- **Translating on appearance:** `static/i18n.js` is loaded in the `<head>` after the language files and watches the page with a `MutationObserver`. Every new text and the attributes `title`, `placeholder` and `aria-label` are looked up, so also everything that `app.js` draws later, messages (`toast`) and the browser dialogs `confirm`/`prompt`/`alert`. `app.js` thus stays almost entirely English.
- **Never user content:** Chats, answers (`.md`), emails, file names, chat and document titles, model names and input fields are in `SUNAK_SKIP_TEXT` and are never translated, even if they happen to equal an interface text.
- **Composed texts** (with names, numbers, plurals) are translated explicitly by `app.js` with `tr('Delete “{title}”?', { title })` or `trn(n, '{n} file', '{n} files')`. Keys with placeholders and at least ten fixed characters also match finished texts; this also translates server messages ("Searching the web: …"). More general keys such as `Remove {name}` apply only to `tr()`, so that they do not hit foreign texts. Server messages that the language file does not know stay English.
- **Setting:** `language` in the settings (`""` = the browser's language, otherwise a value from `LANGUAGES` in `server.py`). The browser keeps a copy in `localStorage` (`sunak-lang`) so that the page starts in the language immediately, also the login page; if it differs from the setting (another device), the page reloads once. A language change reloads the page.
- **New language:** copy `lang-de.js`, translate the texts, include the file in `index.html` and `login.html` before `i18n.js` and add the code to `LANGUAGES`. `tests/test_i18n.py` checks that all texts of the pages and all `tr()` calls are translated, the placeholders match and no translation itself looks like an English text again.

## Configuration

Installer options: `install.sh --yes --no-ollama --no-start --no-shortcut --autostart`; on Windows correspondingly the environment variables `SUNAK_YES`, `SUNAK_NO_OLLAMA`, `SUNAK_NO_START`, `SUNAK_NO_SHORTCUT`, `SUNAK_AUTOSTART`, each set to `1`. Both also know `SUNAK_HOME` (the installer's folder), `SUNAK_REPO` and `SUNAK_BRANCH` (source of the update).

Environment variables of Sunak itself: `SUNAK_HOST`, `SUNAK_PORT`, `SUNAK_DATA`, `SUNAK_PASSWORD`, `SUNAK_NO_BROWSER`, `SUNAK_DEBUG` (log level DEBUG), `SUNAK_REPORT_REPO` (repository for error reports, default `M4XM77R/Sunak`), `SUNAK_ALLOWED_HOSTS` (further allowed host names, comma-separated, `*` for all; protection against DNS rebinding in `Handler.host_allowed`), `SUNAK_MODEL_SLOTS` (simultaneous requests to a local model, default 1; see queue), `SUNAK_GPU` (Docker only, `nvidia` or `amd`), `OLLAMA_BASE_URL`, `ANTHROPIC_API_KEY`, `SEARXNG_URL`, `NO_COLOR`. Docker Compose additionally reads `APP_BIND` (default `127.0.0.1`) and `APP_PORT` (default `7000`). Everything else is set in the interface and stored in the database.

## Tests

```bash
python3 -m unittest discover tests -v
```

The tests start Sunak and simulated servers that imitate the Ollama, Anthropic and OpenAI APIs (as well as IMAP, SMTP, CalDAV, MCP, Whisper, Automatic1111, ComfyUI and GitHub); nothing goes to the real network. Installers can only be checked statically. GitHub Actions runs everything on Linux, macOS and Windows (`.github/workflows/test.yml`).

| File | Checks |
|---|---|
| `test_server.py` | End to end: chat, streaming, thought process, regenerate, memory notes, Compare, Research, documents, model download, Ollama status and catalog, Claude (streaming, headers, refusal, key masking), chat search and export, knowledge base, database migration, login, CSRF protection, path traversal |
| `test_robustness.py` | Hostile PDFs, wrong data types in requests, login after a restart with `SUNAK_PASSWORD`, API keys on redirects to other hosts, stopping through a reverse proxy |
| `test_extract.py` | Text extraction from PDF, Word, OpenDocument, PowerPoint and the knowledge base (test files are created in the test) |
| `test_toolrun.py` | Tool loop: tool calling per backend (Claude, Ollama, OpenAI-compatible) with a simulated MCP server, text protocol, approvals, stop, removed agent endpoints, old chats with agent steps (`toolbackend.py` provides the simulated models) |
| `test_mcp.py` | MCP: simulated stdio and HTTP server, tool lists, calls, secrets, crash and restart, approvals in the chat |
| `test_mail.py` | Mail against a simulated IMAP and SMTP server (also without `MOVE`/`UIDPLUS`), attachments, moving, deleting, new mail, self-test |
| `test_calendar.py` | iCalendar, recurrences across daylight saving time, time zones, writing, simulated CalDAV server, ICS subscriptions, event from text |
| `test_memory.py` | Automatic memory: facts, secrets and duplicates, explicit "merk dir" |
| `test_profiles.py` | Profiles: choice with a PIN, separate data, own settings, admin rights |
| `test_vision.py` | Pictures in the chat: checks, storage, format per backend, models without image understanding |
| `test_websearch.py` | Web search in the chat: switch, sources, reworded follow-up question, error cases |
| `test_log.py` | Logging: format, levels, rotation and size limit of the file, file permissions, masking of secrets, no contents in the request lines, `sunak logs` |
| `test_usage.py` | Token counter: one mocked answer per adapter (Ollama, OpenAI-compatible, Claude, and the three streams of the tool loop), missing numbers stay NULL, a broken counter never makes the request fail, aborted requests, `stream_options` fallback, kinds by path, threads, sums, separate counter per profile |
| `test_reports.py` | Error reports: anonymization, content without variable values, fingerprint, modes (off, ask, automatic), sending against a fake GitHub (new issue, comment, closed issue, rate limit), the token is never output |
| `test_research.py` | Search queries from Qwen-style answers, search engine fallback (DuckDuckGo, Lite, Bing), honest error messages, picture request check in every path |
| `test_intent.py` | Recognition of picture requests: clear/unclear/no picture request (German and English), description without the request, the chat model's answer, endpoint with rules, chat model and images not set up |
| `test_assistant.py` | Events and e-mails from the chat: recognition (German and English, questions and reports are not requests, picture requests stay pictures), e-mail drafts from the model's answer, both endpoints (no model call for the check, no account, nothing saved or sent) |
| `test_queue.py` | Queue (order, places, several places, cancel, timeout), waiting time in the chat until a place is free, automatic picture request with prompt improvement |
| `test_imagegen.py`, `test_sdcpp.py` | Image generation (Automatic1111, ComfyUI, own image program) and model search against simulated servers |
| `test_speech.py` | Voice input to a simulated Whisper server of both kinds |
| `test_gpu.py` | GPU detection with simulated output, sysfs trees, registry, warning, recommendation |
| `test_lan.py` | Phone access (only with a password, second server, QR matrices) |
| `test_themes.py`, `test_i18n.py`, `test_icons.py` | Interface: themes (same names, contrast), languages (all texts translated), icons without emojis |
| `test_cli.py`, `test_desktop.py` | Help and typo hints, `status`, `stop`, autostart files |
| `test_updates.py` | Update check, update button and the changelog of the remote with real Git repositories |
| `test_changelog.py` | Changelog parser, version range, this repo's `CHANGELOG.md`, `sunak changelog` and the question before the update |
| `test_installers.py`, `test_uninstall.py` | Installers (static) and `sunak uninstall` |

## Extending

- **New API endpoint:** write a method on `Handler` and register it in `ROUTES`; exceptions of type `ValueError` are answered automatically as 400.
- **New model in the catalog:** add an entry to `CATALOG` in `sunak/ollama.py` (Ollama name, title, size in GB, tags, description).
- **New backend type:** extend `list_models` and `chat_stream` in `providers.py` with the type and allow the type in `App.save_settings`.
- **New view:** create a `<section class="view" id="view-…">` and a navigation button in `index.html`, add the logic as a section of its own in `app.js` and hook it into `show()`.

## Queue for model requests

Several users (profiles, phone, other devices) share the same backends, so requests wait in a line, **first in, first out** (`sunak/jobqueue.py`).

- **One line per backend:** `chat:<provider id>` for every chat model provider (`providers.queue_key`), `image` for the image generator. Local backends (`providers._is_local`) have `SUNAK_MODEL_SLOTS` places (default 1: one heavy request at a time), backends on the internet four.
- **Where the place is held:** `providers.chat_stream` (and with it `chat_once`: search query, memory, prompt improvement, mail and calendar help) and in `toolrun.ToolRun._turn` around every single model call (the three tool protocols call `providers._request` themselves) and in `/api/imagine` around the image generation. The place is never held while the tool loop waits for the user's approval. Prompt improvement and painting are two separate places in two lines and never hold both at once.
- **Display:** `start_stream` attaches a `notify` to the request thread (`jobqueue.local`) that writes `{"type": "queued", "position": n}` into the NDJSON stream (only when waiting; finally `position: 0`). The browser shows "Waiting in the queue: place n" in the chat status, as a notice in the tool steps and in the picture placeholder. Events go out at least every two seconds; if writing fails (Stop, tab closed), the request leaves the line without ever going to the model. Requests without a stream (for example `/api/calendar/parse`) wait silently.
- **Limits:** If a request waits longer than 15 minutes, the user gets an error message. The line lives in memory and applies per Sunak process; requests that do not run through Sunak (Ollama by hand) are not seen by it. The image generator and the chat model on the same graphics card are two separate lines; if both are under load, they share the card.

## Token counter

The counter hangs in `providers.chat_stream` (one hook for all paths, including `chat_once`) and in the three streams of the tool loop (`toolrun._metered` around `ClaudeTurns.turn`, `OllamaTurns.turn`, `OpenAITurns.turn`; `TextTurns` runs through `chat_stream`). The record is written at the end of the request, also on error (`ok` = 0) or when the reader stops early (`ok` = 1). Without a profile context (tests, scripts) or with no answer at all, nothing is stored. For OpenAI-compatible servers `providers.open_openai_stream` sends `stream_options.include_usage`; if a server's error message (HTTP 400 or 422) names the option `stream_options` or `include_usage`, the same request follows without it, and if that does not fail, `_NO_STREAM_USAGE` remembers the address. Every other error (context too long, unknown model, tools not supported) goes on immediately and without a second attempt. The display fetches `GET /api/usage` after every stream (`usageSoon`: immediately and after five seconds for the background requests), at startup and when the settings are opened.

## Error reports

The reports land in a public repository (warning in the settings, confirmation when switching on "auto", a note on the report and in the issue). Details about content, anonymization and duplicates are at `sunak/reports.py` (table Files) and in the README (Error reports). Flow: an error that is logged with a traceback (`log_http.error` on HTTP 500, `log_app.error` for unexpected errors, crashed threads) goes to `Reports.capture`. With `off` nothing happens. Otherwise a report is created in `reports.json` (at most 20 waiting; the same error counts up). With `auto` and a token a background thread sends it immediately, otherwise the user decides in Settings → Error reports. When sending: first the rate limit, then a search for the fingerprint in the issue titles, then a comment or a new issue. An error while sending (no network, token rejected) lets the report wait; the server's error message (`ReportError`, a `ValueError`, so HTTP 400) appears as a notice. Sending itself logs only WARNING so that there is no report loop (`_local.busy` protects in addition).

## Logging

Everything goes through `sunak/log.py`; no `print` for operating messages (the startup display in `__main__` stays).

- **Where to:** terminal (stderr) and `<data folder>/logs/sunak.log`. The file rotates at 10 MB (`MAX_BYTES`) and keeps four backups (`BACKUPS`), so at most 50 MB in total; `os.chmod 600`. If the folder cannot be created, Sunak logs only to the terminal and says so once. Terminal line: `HH:MM:SS LEVEL area text`, file line with the date.
- **Levels:** INFO in normal operation, DEBUG with `SUNAK_DEBUG`. Requests (`Handler.route`): changing API calls INFO, reading and static ones DEBUG, 4xx WARNING (except 401/404 on read and page requests: DEBUG), 5xx ERROR; for streams an error event appears in the line (`stream error: …`, cut to 200 characters). Uncaught errors with a stack trace (`exc_info`). Queue: waits ("busy, … place n"), its turn ("its turn after …"), left, timeout. Pictures: job (program, format), prompt improvement (model, duration, fallback), result (duration, size, steps) or error. Also start and end, update checks and installation, model errors (provider and shortened message).
- **What never gets in:** contents of chats, prompts, answers, mails, files; passwords, API keys, tokens, cookies; query strings (only the path is logged). In addition every line including the stack trace runs through `redact`. New log calls may therefore name only metadata (model id, duration, count), never `request`, `prompt` or message texts.
- **`sunak logs [LINES]`:** `log.tail` reads the end of the file (at most 256 KB) and prints the path and lines.
