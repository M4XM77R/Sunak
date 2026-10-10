<p align="center">
  <img src="sunak/static/icon.svg" width="72" alt="">
</p>
<h1 align="center">Sunak</h1>
<p align="center">
  Your private AI workspace: chat, model comparison, web research, documents and memory.<br>
  Runs entirely on your own computer, in pink, with a focus on easy installation.
</p>

> [!WARNING]
> **Completely vibe coded.** Sunak was written entirely by an AI (Claude), including the installer, the tests and this guide. No human has reviewed the code line by line. The automated tests do run on Linux, macOS and Windows, but there can still be bugs and security holes. Use it at your own risk. Do not expose Sunak to the internet without protection, and do not put sensitive data into it without backing it up separately.

<p align="center"><img src="docs/chat.png" alt="Chat" width="820"></p>
<p align="center"><sub>The screenshots in <code>docs/</code> come from an early version and may no longer match the current interface (for example the sidebar has since gained Knowledge, Mail and Calendar and uses line icons instead of emojis).</sub></p>

**Contents:** [Installation](#installation) · [First steps](#first-steps) · [Features](#features) · [Guides](#guides) · [Commands](#commands-sunak--h) · [Configuration](#configuration) · [Updating and uninstalling](#updating-and-uninstalling) · [Troubleshooting](#troubleshooting) · [Development](#development)

## Installation

One line is enough. Sunak needs **no Python packages**, only Python 3.9 or newer, and the installer fetches it if necessary.

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/M4XM77R/sunak/main/install.sh | bash
```

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/M4XM77R/sunak/main/install.ps1 | iex
```

The installer

1. checks for Python 3.9+ and installs it if needed,
2. creates the `sunak` command,
3. asks whether to put a Sunak icon on the desktop (on Linux also in the app menu, on macOS as `Sunak.app` in `~/Applications`, on Windows also in the Start menu). The icon starts Sunak without a terminal window, or just opens it if it is already running,
4. asks whether Sunak should start automatically in the background when you log in (default: no),
5. shows which graphics card Ollama can use and offers to install [Ollama](https://ollama.com) for local models,
6. asks whether to also install the optional [desktop app](#desktop-app-optional) (default: no),
7. starts Sunak and opens the browser at `http://localhost:7000`.

Without a terminal (for example in a pipe with no input) the defaults apply to yes/no questions. For an installation with no questions at all there are options, see [Installer options](#installer-options).

**Try it without installing:**

```bash
git clone https://github.com/M4XM77R/sunak.git
cd sunak
python3 start.py
```

On Windows a double click on `start.py` is enough. This way there is no `sunak` command, and updating means `git pull`.

**Docker (including Ollama):**

```bash
docker compose up -d                                                   # CPU only, http://localhost:7000
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d   # with an NVIDIA GPU
docker compose -f docker-compose.yml -f docker-compose.amd.yml up -d   # with an AMD GPU (Linux)
```

Your data then lives in the `data/` folder next to the Compose file (Ollama models in `data/ollama/`). By default the port is open only on your own computer; `APP_BIND=0.0.0.0` (all networks) and `APP_PORT=8123` (another port) change that, and `SUNAK_PASSWORD=…` sets a password (all three as environment variables before `docker compose`, or in an `.env` file). NVIDIA needs the NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) on the host; AMD needs the `amdgpu` driver (Linux, ROCm image `ollama/ollama:rocm`). On a Mac, Docker cannot use the GPU; the normal installation with the Ollama app is faster there.

## First steps

1. On the first start Sunak detects your memory (and graphics card) and suggests a suitable model: up to 6 GB RAM `qwen3:1.7b`, up to 12 GB `qwen3:4b`, up to 24 GB `qwen3:8b`, above that `qwen3:14b`. If a larger model fits completely into the graphics memory, Sunak suggests that one.
2. One click downloads the model (with a progress bar; you can cancel at any time and the next try resumes). Then you can chat right away.
3. Prefer a cloud model? On the first start choose "Use Claude with an API key", or later enter a provider under Settings → Providers (Claude, OpenAI, OpenRouter, Groq, LM Studio, llama.cpp, vLLM).
4. The Settings page has a search box at the top: type a word (for example "reminder" or "memory") to show only the matching sections and settings.
5. To quit Sunak: Settings → Stop Sunak, or `sunak stop`. To start it again: the desktop icon, or `sunak`.

**Interface language:** The interface follows your browser's language (English or German, switchable under Settings → Look → Language). This guide uses the English menu names.

## Features

| | |
|---|---|
| 💬 **Chat** | Streaming answers, full-text search across all chats, export (Markdown, JSON, PDF), edit and regenerate, Markdown, tables, code with a copy button, collapsible thought process of reasoning models, attach files and images |
| 🤖 **Providers** | Ollama (local), Claude (Anthropic API) and any OpenAI-compatible API (OpenAI, OpenRouter, Groq, LM Studio, llama.cpp, vLLM) |
| 📚 **Knowledge** | Your own knowledge base from PDF, Word, OpenDocument, PowerPoint, HTML, Markdown, text, CSV and code, with source references in the answers |
| 🌐 **Web search** | Globe button in the chat: Sunak searches, reads the best pages and answers with sources |
| 🔎 **Research** | Thorough report with sources from several searches, can be saved as a document |
| 📝 **Documents** | Markdown editor with autosave, preview, export and AI editing |
| 🧠 **Notes & Memory** | Notes and a memory that Sunak builds from your chats by itself |
| 📄 **Office files** | Documents and tables as real files: Word (.docx), LibreOffice (.odt, .ods), Excel (.xlsx) and, with LibreOffice installed, PDF; ask in the chat or use `/dokument` |
| ✉️ **Mail** | Several accounts via IMAP/SMTP; the AI summarizes, drafts replies and sorts the inbox; new mails can be prepared from the chat |
| 📅 **Calendar** | Own calendar, CalDAV and subscribed calendars; events from one sentence or from a mail, or straight from the chat |
| 🔢 **Token counter** | Counts the tokens of every model request per profile (input, output, cache) with tokens per second and a running total |
| 🔌 **Tools (MCP)** | Any MCP server as tools for the model |
| 🎨 **Image generation** | With Sunak's own image program (stable-diffusion.cpp), Automatic1111 or ComfyUI |
| 🖼 **Image understanding** | Send photos and screenshots to vision models |
| 🎤 **Speaking and reading aloud** | Dictation (locally with Whisper or Chrome) and reading answers aloud |
| ⚖️ **Compare** | One prompt to 2 to 4 models at the same time |
| 🎭 **Personas** | System prompts you can switch between (Assistant, Coder, Writer, Translator, Teacher and your own) |
| 🧩 **Models** | Model search, catalog with recommendations, GPU detection, start and install Ollama |
| 🎨 **Themes** | Eight themes and custom accent colors, installable as an app (PWA) |
| 🌍 **Languages** | Interface in German or English |
| 👥 **Profiles** | Several people on one Sunak, each with their own data and an optional PIN |
| 🐞 **Error reports** | Optional: unexpected errors are reported as a GitHub issue, without chats, prompts or keys (off by default) |
| 📱 **Phone access** | On your Wi-Fi via QR code |
| 🔒 **Security** | Only on `localhost` by default, optional password, data in one SQLite file |

<p align="center"><img src="docs/models.png" alt="Models" width="820"></p>
<p align="center"><img src="docs/onboarding.png" alt="First start" width="410"> <img src="docs/compare.png" alt="Compare" width="410"></p>

## Guides

### Chat

| Action | How |
|---|---|
| Send / new line | `Enter` / `Shift+Enter` |
| New chat | `Ctrl+K` (Mac: `⌘K`) |
| Slash commands | Type `/` at the start of the message box for the list (German or English names): `/termin` (`/event`), `/mail`, `/dokument` (`/doc`), `/bild` (`/image`), `/web`, `/heute` (`/today`), `/woche` (`/week`), `/wissen` (`/knowledge`), `/modell` (`/model`), `/persona`, `/neu` (`/new`), `/export`, `/suche` (`/search`), `/zusammenfassen` (`/summarize`), `/hilfe` (`/help`). Details below |
| Switch model | Selector at the top right |
| Switch persona | Selector at the top next to the model, applies to the current chat. Your own personas: Settings → Personas |
| Find old chats | Search box above the chat list: searches titles and all messages, a click jumps to the spot |
| Export a chat | Download button at the top right → Markdown, JSON or Print/PDF |
| Back up everything | Settings → Data → Download backup: one JSON file with chats, documents, notes, knowledge base, calendar events, settings, mail and calendar accounts, but without API keys, passwords and pictures |
| Restore a backup | Settings → Data → Import backup (or `sunak import FILE`): adds the backup, or a single chat exported as JSON, to the profile you are in. Nothing is overwritten: chats, documents and notes with the same id (notes also with the same text), knowledge-base files with the same name, calendar events with the same id, mail accounts with the same address and calendar accounts with the same address are skipped, and a setting is taken over only when you have not set it yourself. Settings of the whole installation and model providers only come in from an admin profile. The result lists what was added and skipped and which passwords and API keys you have to enter again. Only import files you trust |

**The input box:** Next to it on the left are the paperclip (attach files and images), the **+** and, on the right, Send. The **+** menu opens upwards and contains Knowledge base, Web search, Tools (MCP) and Speak, each with an on/off switch. Tools (MCP) appears only when a server is switched on, and only for admin profiles; Speak appears as long as voice input is not switched off. This leaves room for typing on a phone.

**Slash commands:** `/` at the start of the message box opens a list of commands; arrow keys and `Tab`/`Enter` pick one, `Esc` closes it. `/termin morgen 10 Uhr Zahnarzt` and `/mail an Anna: komme später` show the usual event or e-mail card (nothing is saved or sent before your click), `/dokument a letter to my landlord` writes a document or table as a file card (see Office files), `/bild a cat in a hat` paints a picture, `/web <question>` answers with a web search and `/wissen <question>` from your knowledge base only, each for this one message and without changing the switches in the **+** menu. `/heute` and `/woche` list your calendar entries for today or the next 7 days, `/modell <name>` and `/persona <name>` switch by (part of) the name (without a name you get a list to click), `/neu [message]` starts a new chat, `/export [md|json|print]` exports the open chat, `/suche <words>` searches all chats, `/zusammenfassen [focus]` asks the model for a short summary of the chat, and `/hilfe` shows this list. `/web`, `/wissen` and `/zusammenfassen` are sent as a normal message; they do not work with Tools (MCP) switched on. A path like `/etc/hosts` is not a command; a message that is only a single word with a slash (`/tmp`) is taken for one, so type two slashes (`//tmp`) to send it as text.

**Attaching files:** Paperclip or drag and drop. Text, PDF, Word and PowerPoint are read and added to the message. For many files that should stay available, the knowledge base is better.

**Asking about an image:** Attach an image, drag it into the chat window or paste a screenshot with `Ctrl+V`, write your question, send. This needs a model that understands images (for example `qwen2.5vl:7b` or `gemma3:4b` under Models, `llama3.2-vision`, or Claude). Other models say so right away, and the message stays in the input box. PNG, JPEG, GIF and WebP are allowed, up to 4 images per message and 5 MB per image; Sunak shrinks large photos before sending.

**Asking about your own files (Knowledge):** Knowledge → drag files in (PDF, Word, OpenDocument, PowerPoint, HTML, Markdown, text, CSV, code) → in the chat switch on "Knowledge base" via the **+**. The answers name the files they come from. If the knowledge base is small (up to about 8000 characters), the model sees all of it, otherwise the best sections. Sunak cannot read scanned PDFs without a text layer or encrypted PDFs. Everything stays local.

**Asking about current events (Web search):** In the **+** menu switch on "Web search" (per chat, off by default), then ask as usual. Sunak searches DuckDuckGo (no account needed; if DuckDuckGo blocks it or is unreachable, Sunak tries DuckDuckGo Lite and Bing) or your own SearXNG instance (`SEARXNG_URL`), reads up to four pages, and the model answers with sources [1], [2] that are clickable above the answer. For follow-up questions the model writes the search query itself. The search query goes out to the internet. For a detailed report there is **Research**: the model plans up to three searches (if it returns nothing usable, for example only thoughts like some Qwen models, Sunak searches for your question itself), reads up to five pages and writes a report with sources that you can save as a document. If you write a picture request in Research, Sunak paints it in a new chat instead of researching it. If the search fails, the error message says why (search engine blocked, unreachable) and how to work around it (`SEARXNG_URL`); "found nothing" means the search ran but found nothing.

**Using a cloud model:** Settings → Providers → pick a preset (for example "Claude (Anthropic)", API key from [console.anthropic.com](https://console.anthropic.com)) → enter the key → Save settings. Keys stay on your computer and are never sent back to the browser. With the environment variable `ANTHROPIC_API_KEY`, Sunak sets up Claude by itself on the first start.

**Introduction:** The first time a profile is used, a short tour opens (six steps, skippable with the button or `Esc`). It stays away afterwards; Settings → Introduction → "Show the introduction" opens it again. Profiles that already existed see it once after the update to 0.20.0.

### Automatic memory

After an answer, the chat's model checks whether the last question and answer contain lasting facts about you (name, job, preferences for answers) and stores them as a note tagged "memory", at most three per answer. You see this as a notice with **Undo**, and under Notes & Memory, there with the chat it came from. The AI knows all memory notes in every chat. "Remember that …" is always saved; passwords, keys, PINs and card numbers never are. It does not run with tools switched on, after picture requests or when memory is switched off. To switch it off: Settings → Chat → "Remember things about me from chats by itself" (only the automatic half) or "Use memory notes in chats" (no memory at all).

### Models, GPU and search

Sunak does not compute anything itself; the models run in Ollama. Ollama uses a suitable GPU automatically: NVIDIA via CUDA, AMD via ROCm, Apple Silicon via Metal. The Ollama installer sets everything up; an NVIDIA card only needs the normal driver. Without a suitable GPU (NVIDIA or AMD with at least 3 GB of graphics memory, or Apple Silicon) the models run on the processor, and then small models are the better choice.

- **Web search stays on the internet:** Pages that a search finds are only read from public internet addresses, also after redirects. Addresses on your own computer or network (`localhost`, `192.168.…`, `10.…`, `169.254.…`, IPv6 equivalents) are refused, so a web page cannot make Sunak read from your home network. Your own SearXNG (`SEARXNG_URL`) and Ollama on `localhost` keep working. `SUNAK_ALLOW_PRIVATE_FETCH=1` switches this off, for research on an intranet.
- `sunak gpu` shows which GPU Sunak found; the installers report it as well.
- The **Models** page (admin profiles only) shows the GPU and graphics memory, marks models that fit completely with "fits GPU", and shows for each loaded model whether it runs on the GPU or the processor. If Ollama runs on the processor despite a GPU, a warning with a hint appears.
- Ollama can be started from within Sunak, and on Windows (winget) and macOS (Homebrew) also installed; on Linux Sunak shows the command of the official installer.
- **Busy backend:** When a backend (for example an Ollama that is busy with a large request) needs long to list its models, Sunak shows the list from its last success and marks it "busy, last list shown" instead of "offline". A refused connection or a wrong key still shows the error. If no model can be loaded at all, the picker says "Models could not be loaded" and shows the reason on hover.
- **Downloading a model:** Models → pick a model → Download. Any Ollama model also works by name. Installed models can be deleted there.
- **Searching for models:** The search box instantly filters Sunak's catalog (filters: All, Chat, Vision, Coding, Reasoning, Image; size; fits your computer). "Search online" additionally asks ollama.com and Hugging Face; without a network it quietly stays with the own catalog. For Hugging Face results, "Show files" shows size, quantization and license; Download loads the GGUF model through Ollama (`hf.co/…`) or, for an image model, into Sunak's image program. Sunak cannot download models that require a Hugging Face login.
- AMD cards that ROCm does not officially support often work with `HSA_OVERRIDE_GFX_VERSION` (for example `10.3.0` for RX 6000, `11.0.0` for RX 7000), set for the Ollama service or in the `ollama` container. Details: [docs.ollama.com/gpu](https://docs.ollama.com/gpu).

### Tools (MCP)

MCP servers (Model Context Protocol) give the model tools: files, reading web pages, the time, memory, or any other MCP server, as a program on the computer (stdio) or via an address (Streamable HTTP).

1. Settings → Tools (MCP) → choose "Preset…" (Files in a folder, Read web pages, Time and time zones, Memory as a knowledge graph) or "Add server".
2. Name, type "Program" with the start command (for example `npx -y @modelcontextprotocol/server-memory`, needs Node.js; `uvx mcp-server-fetch` needs uv) or "Address (HTTP)" with the URL and optionally a token.
3. Enter secrets such as the server's API keys as `NAME=value` under the environment variables. They stay on the computer and are never sent back to the browser.
4. "Test" starts the server once and shows its tools, then Save settings.
5. In the chat switch on "Tools (MCP)" via the **+**.

Before every tool call Sunak asks ("Allow", "Allow … in this chat", "Deny") and shows the input. Only admin profiles set up and use servers; a program server runs with your permissions.

### Several users at once

Sunak can be used by several people at the same time (phone access and profiles: see below). So that a computer does not choke on several large requests at once, requests to a model wait in a queue, **first in, first out**: whoever asks first is served first. Every backend has its own queue (each chat model program separately, the image generator separately). While your request waits, the chat shows "Waiting in the queue: place n" (for images in the placeholder); once it is its turn, it runs as usual. **Stop** or closing the page removes a waiting request from the queue. A local model handles one request at a time (`SUNAK_MODEL_SLOTS` changes that), a model on the internet four at a time.

### Image generation

Picture requests in the chat are handled by Sunak by itself, without asking back and with any chat model: if you write "make me a picture of a lighthouse in landscape format", "draw me a cat", "Bild von einem Fuchs", "a picture of: a snowy landscape" or "generate an image of …" (German and English; not with attachments), the chat model first turns your request into a better English prompt, and that goes to the image model. Once images are set up, for every message that is not already clearly a picture request ("generate me a picture of …" is painted without asking), Sunak briefly asks the chat model for a yes or no on whether it is one (only the last message, only the first words of the answer; this also recognizes sentences without a picture word such as "A fox in the snow, photorealistic", while "How do I create an image in Photoshop?" stays a chat). That costs one small extra call per message and can be switched off in Settings → Image generation under "Recognise picture requests with the AI". If the model does not answer (error, more than 15 seconds, or it is busy with other requests), patterns decide: anything that is not clear goes to the normal chat. Clear are requests like "generate me a picture of …", "a picture of: …" or "draw a cat". Below the picture you see the "Improved prompt", size, seed and steps; "Again" paints a new variant with the same prompt, and there are Download and Stop (which also cancels a waiting request). The format follows the request (landscape, portrait, otherwise square). If the improvement fails, your description goes to the image model unchanged. The pictures stay in the chat. Image generation is off by default; as long as it is not set up, a hint on a picture request names the missing step, and the message goes to the model as a normal chat.

**With Sunak's own image program (stable-diffusion.cpp), without Python packages:**

1. Models → filter "Image" → "Set up the image program": Sunak suggests the right version (NVIDIA: CUDA, other graphics cards: Vulkan, Mac: Metal, otherwise processor only), Install. Depending on the version the program is about 20 to 500 MB (CUDA is the largest).
2. Download an image model: SD-Turbo (to start with, 5 GB), SD 1.5, SDXL-Turbo, SDXL, or one found via Hugging Face search, with license notice, progress, pause/resume and delete. Models are 4 to 8 GB.
3. Ask for a picture in the chat. Sunak guides you through the steps: if something is still missing, the Models page shows "Next step", and a picture request in the chat names what is missing. When the program and a model are there, Sunak picks the model itself.

With a graphics card a picture takes seconds, with only the processor one to several minutes. Error messages of the program appear in the chat.

**With Automatic1111 / Forge / ComfyUI:** Install a Stable Diffusion program, for example [Automatic1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui) or Forge (start it with the `--api` option) or [ComfyUI](https://github.com/comfyanonymous/ComfyUI), and put a model in it. Then Settings → Image generation → choose the program, leave the address empty for the usual local one (`http://127.0.0.1:7860` or `:8188`), "Test" shows the models → Save settings. For SDXL and Flux models choose the image size 1024 px.

### Speaking and reading aloud

- **Dictation:** In the **+** menu click "Speak", talk, click again; the text lands in the input box and is sent only when you click.
- **Fully local with Whisper:** for example start whisper.cpp with `whisper-server -m ggml-base.bin` and enter `http://localhost:8080/inference` under Settings → Voice (Speaches/faster-whisper-server/LocalAI: `http://localhost:8000/v1` and the model name).
- **Without Whisper** Sunak uses the offline recognition of Google Chrome (version 139 and later). The normal online recognition (Chrome sends the audio to Google) is used only if it is allowed under Settings → Voice; there the microphone can also be switched off entirely.
- The microphone only works on the computer itself (`localhost`) or over https, not through phone access; on a phone the keyboard's dictation helps.
- **Reading aloud:** Speaker button under an answer, click again to stop. It uses the voices of the device; choose a voice under Settings → Voice (per device, with a ▶ test).

### Office files

Sunak writes real files from what the model writes: **Word** (`.docx`), **LibreOffice** (`.odt` and, for tables, `.ods`) and **Excel** (`.xlsx`). They are made by Sunak itself (ZIP + XML from the Python standard library), so LibreOffice does not have to be installed. If LibreOffice is installed (`soffice` on the path, or in its usual folder on macOS and Windows), **PDF** is offered too.

- **Ask in the chat:** "make me a one-page letter to my landlord as a Word file", "a table of the planets with mass and distance". The model answers with a **document card** that shows the text; one click downloads the file type you want. Nothing is stored on the server.
- **`/dokument <what>`** (`/doc`) does the same without relying on the model to notice the request.
- **Under any answer:** the **As document** button turns that answer into a card.
- Headings, paragraphs, bullet and numbered lists, **bold**, *italic*, `code` and tables are carried over. For a spreadsheet, every table becomes a sheet named after the heading above it; plain numbers become numbers (a text like `007` stays text), and text starting with `=` is never turned into a formula.
- Limits: 400,000 characters of text, 200,000 table cells. PDF is made by LibreOffice and can take a few seconds.

### Mail

Sunak speaks IMAP (reading) and SMTP (sending) directly with the Python standard library, without extra packages and without detours through third-party servers.

**Linking an account:** Settings → Mail accounts → Add mail account → enter address and app password (the servers are filled in automatically for Gmail, Outlook, iCloud, Yahoo, GMX, WEB.DE and Telekom; your own servers work too) → Test connection → Save account. As many accounts as you like. Handling mail with the AI: Mail → open a mail → Summarize, Reply and then Draft reply (optionally with a hint like "accept, but only next week"), or "Ask in chat"; "Overview" sorts the inbox ("what needs a reply, what can wait").

What works: inbox per account, folders, search, reading mails without marking them as read, downloading attachments, replying, forwarding (with the attachments), own attachments, drafts, moving, deleting via the trash.

- **App password:** Gmail, iCloud and Yahoo require an app password instead of the normal password (for Gmail only after switching on 2-step verification, then at https://myaccount.google.com/apppasswords). For GMX and WEB.DE, IMAP must first be enabled in the mailbox settings; for Telekom your own email password applies. Sunak shows the matching hint during setup.
- **Security:** Passwords, like API keys, live only in the local database, are never logged and never returned to the browser; the backup does not contain them. Connections use SSL/TLS or STARTTLS with certificate checking. Unencrypted (and with a self-signed certificate) Sunak connects only to `localhost`, for example with the Proton Mail Bridge.
- **Nothing happens on its own:** Folders are opened read-only, mails stay unread. Mail is sent only after you click **Send** and confirm, drafts reach the Drafts folder only with **Save draft**. AI replies appear as a draft in the form.
- **Attachments:** The paperclip in the form attaches files (at most 17 MB in total). When forwarding, the attachments of the original mail come along; each can be removed beforehand with the x.
- **Moving and deleting:** In the reading view "Move to…" and Delete. Deleting moves to the trash after confirmation; permanent deletion happens only in the trash (or for accounts without a trash), with its own confirmation. In Gmail, folders are labels: moving removes the old label and sets the new one, deleting puts the mail in the trash, where Google removes it by itself after 30 days.
- **New mail:** While Sunak is open, it looks into every inbox every 2 minutes (read-only). New unread mails announce themselves with a notice, and the Mail button shows the number of unread mails. With "Also as desktop notification" (Settings → Mail accounts) the message also arrives as a desktop notification when Sunak is in the background (only over `localhost` or https). To switch it off, untick "Tell me about new mail".
- **From the chat:** Write "write Anna an email that I'll be late" or "schreib Anna eine Mail, dass ich später komme" in a normal chat (German and English, not with attachments). Sunak recognizes the request by itself, with any model, and shows a card with recipient, subject and text: **Open in Mail** puts the draft into the compose form, where sending still needs your click on **Send** and a confirmation. Without a linked mail account the card says so and offers "Add mail account". If you give an address, it is used; without one the recipient stays empty. If the request is worded in a way the patterns do not catch, the model itself knows that Sunak can prepare e-mails and answers with the same card (a model that follows instructions is enough). Questions ("How do I write an email to my boss?") stay normal chats; if Sunak guesses wrong, **Send as normal message** on the card sends your text to the model as usual.
- **Mail content is not a command:** The AI receives mails explicitly as data from third parties and is told to ignore instructions in them. It has no tools anyway and cannot send anything by itself.
- **Testing a real account:** `sunak mail-selftest` (with `--account address` when there are several accounts) checks a linked account step by step against the real provider: login, reading the inbox, new-mail notice, sending to itself with an attachment, forwarding as a draft, moving, deleting. Every test mail carries a random marker in the subject, only these mails are touched and at the end permanently deleted (`--keep` keeps them). The password is never printed; with `--new` you type in address and app password instead (not saved).

**Limits (honestly):**

- **No OAuth.** Login works only with a password or app password. OAuth would need an app registered with Google or Microsoft; that cannot be shipped cleanly without a third-party service. Microsoft (Outlook, Hotmail, Microsoft 365) often allows only OAuth for third-party programs. If the server rejects the login, the account does not work in Sunak.
- HTML mails are shown as text (no images, no formatting, and therefore no tracking).
- The new-mail notice comes only while Sunak is open in the browser (no background service, no IMAP IDLE), with up to 2 minutes of delay. Every action opens a new connection, which takes one to two seconds depending on the provider.
- Moving and deleting work per mail, not for several at once.
- The automated tests run against simulated servers; against a real provider `sunak mail-selftest` checks on your computer.

### Calendar

Month view with all calendars: Sunak's own calendar, CalDAV accounts (iCloud, GMX, WEB.DE, Yahoo, mailbox.org, Posteo, Fastmail, Nextcloud or your own address) and subscribed calendar addresses (ICS, for example Google or Outlook, read-only). Create, change and delete events, also all-day and recurring; recurrences, time zones and daylight saving time are calculated correctly. You choose which calendars are shown in the list on the right of the calendar.

- **Connecting:** Settings → Calendars → "Add calendar". For CalDAV, under "Own login" choose a linked mail account (address and user name are filled in, the mail account's password is used) or enter provider, user name and (app) password. Google and Outlook.com offer no CalDAV with a password: subscribe to their secret iCal address as "ICS address" instead.
- **Event from text:** In the calendar type a sentence ("dentist next Tuesday 10 am") and click "Add", or in a mail "Add to calendar". The model fills in the form; it is saved only after your click.
- **From the chat:** Write "trag mir morgen 10 Uhr Zahnarzt ein", "add dentist tomorrow 10am to my calendar" or "remind me to call Tom on Friday" in a normal chat (German and English, not with attachments). Sunak recognizes the request by itself, with any model, reads the event with the same model call as "Event from text" and shows a card with title, date and time. **Save** stores it in the calendar you used last (otherwise Sunak's own), **Edit** opens the event form. An event request needs a date or time, and the card warns when the date is in the past. **Send as normal message** hands your text to the model instead if Sunak guessed wrong. Nothing is saved before your click. If the request is worded in a way the patterns do not catch, the model itself knows that Sunak can prepare events and answers with the same card; only the newest answer of a chat can save it. Questions ("What is on tomorrow?") stay normal chats and are answered from your calendar (see below). The cards belong to the open chat only and are not stored with it.
- **Asking about your calendar:** In a normal chat ask "What is on tomorrow?", "Am I free on Friday?" or "Welche Termine habe ich diese Woche?". When a message is about time or the schedule (words like appointment, calendar, today, tomorrow, weekday names, this week), Sunak adds your appointments of today and the next 7 days from all shown calendars to that request, read-only and only for the profile you are using; other messages get nothing, so no tokens are spent. If a calendar cannot be read, the model is told which one instead of assuming nothing is planned. Event texts count as data, never as instructions.
- **Reminders:** In the event form choose "Reminder" (at the start, 5 minutes to 2 days before; for all-day events at 9:00 on the day or before). Turn them on in Settings → Reminders. While Sunak is open you get a notice in the page and, if you allow it, a desktop notification. For push messages on your phone, also when no browser is open, enter an ntfy topic there (see below). Reminders already in events from other calendars (CalDAV, ICS) are used as well.
- **Limits:** Recurrences by week number or day of the year and hourly recurrences are not supported. ICS subscriptions are cached for 5 minutes.

#### Push messages with ntfy

Real Web Push would need encryption that Python's standard library does not have, so Sunak sends reminders through [ntfy](https://ntfy.sh): install the free ntfy app (Android, iPhone), subscribe to a topic, and enter the same topic in Settings → Reminders ("Random topic" makes a hard-to-guess one). "Send test" checks it. Sunak sends the message itself, so it arrives whenever Sunak is running, even with the browser closed; a computer that is off or asleep sends nothing.

- **Privacy:** On the public server ntfy.sh, title, place and time of the event pass through that server, and anyone who knows the topic can read it. Use a random topic, or run your own ntfy server and enter its address (it must accept messages without a login; passwords are not supported). Each profile has its own topic; the server address is a setting of the whole installation that only admin profiles can change. The topic is not part of the backup.
- **How it works:** Every 30 seconds Sunak checks the events of the next 8 days in all profiles that turned reminders on (the calendars are read every 10 minutes, Sunak's own calendar right after a change). Each reminder is sent once. If the ntfy server is not reachable it is tried again until the event starts. A reminder that came due while no page was open, or while Sunak was off, is still shown in the next page that opens, and sent, as long as the event has not started yet.
- **Limits:** Only reminders relative to the start are used (not "at 9:00 sharp" or relative to the end). All-day events use this computer's time zone ("9:00" stays 9:00 on days when the clocks change). Changing a reminder in the event form replaces only the reminder shown there; other reminders of the event stay.

### Profiles

Several people on one Sunak: each profile has its own chats, documents, notes, knowledge base, mail accounts, calendars, personas, theme and language, with a PIN if you like. Providers, models and MCP servers are shared. The token counter also belongs to the profile. There can be at most 20 profiles.

- **Creating:** Settings → Profile → "Add profile": name, optionally an own emoji, optionally a PIN (at least 4 characters) and whether the profile should be admin. The next time you open Sunak it asks "Who is using Sunak?"; you switch via the name at the top left.
- The first profile is the main profile with all earlier data; it always stays admin and cannot be deleted.
- **Rights:** Only admin profiles change providers, models, tools, image generation, voice input, updates, error reports, phone access, the password and profiles.
- **Admin profiles need a PIN:** As soon as there is more than one profile, an admin profile without a PIN can be chosen only on the computer Sunak runs on (not through the network, a phone or a reverse proxy). Anyone else sees a lock on its tile and has to ask you to set a PIN there (Settings → Profile). A device that is already in the profile stays in. "On the computer itself" means: the request comes from this computer, is addressed as `localhost` or an IP address, and carries none of the headers a proxy adds (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `Via`, …). **Behind a reverse proxy on the same computer the proxy must add `X-Forwarded-For`**, otherwise Sunak cannot tell it from a local visit and treats the visitors as local. For nginx: `proxy_set_header X-Forwarded-For $remote_addr;` (or `$proxy_add_x_forwarded_for`) in the `location` block. Safest of all: give admin profiles a PIN.
- **Wrong PINs and passwords:** After 5 wrong tries from the same device the login and the PIN prompt lock for 30 seconds; every further wrong try doubles the wait, up to 15 minutes. A profile or the password as a whole locks the same way after 20 wrong tries from all devices together. The count is made before the password is checked, so many parallel tries cannot slip through. A right answer starts counting again; restarting Sunak clears the locks. **Trade-off:** because the whole installation locks after 20 wrong tries from any devices, someone who keeps guessing from many addresses can lock you out for up to 15 minutes too (restarting Sunak clears it). That is deliberate: a locked door is better than a guessed password.
- A PIN separates the profiles inside the app, but does not protect against someone who can open the files under `~/.sunak` on the computer. The password (Security) applies to the whole installation.

### Token counter

For every model request Sunak counts the tokens and remembers: time, provider, model, input, output, cache read, cache written, duration and tokens per second. This applies to Ollama, Claude and OpenAI-compatible providers, also with tools (MCP). The numbers live in the profile's database and survive a restart.

- **Display:** After the first counted request, a line below the input box shows the tokens and tokens per second of the last request and the total; a click opens Settings → Token counter. There you see the last request in detail, the total, input, output, cache read and written separately, and the part that Sunak requested by itself. Admin profiles additionally see the sum of all profiles.
- **Per profile:** Every profile has its own counter and sees only its own.
- **What counts:** The total consists of input, output, cache read and cache written. Requests that Sunak makes itself (picture check, remembering facts, improving image prompts) count too and are shown separately. "Last request" is the last one you triggered, not one of these background requests. If a request fails or is stopped, Sunak counts what had been reported up to then (for Claude the input; the output stays empty because Claude reports it only at the end).
- **Where the numbers come from:** Ollama reports them at the end of the answer (tokens per second from `eval_count` and `eval_duration`), Claude in `usage` (tokens per second from the measured time between the first and the last output part), OpenAI-compatible servers with the option `stream_options` (Sunak asks for it; if a server rejects it, Sunak asks without it and remembers that). If a provider does not report a number, it stays empty ("–") and is not estimated, for example the cache with Ollama.
- **Never an error:** If counting fails, it is quietly written to the log and the request continues normally.

### Error reports

So that bugs can be found and fixed, Sunak can report unexpected errors as an **issue on GitHub** (repository `M4XM77R/Sunak`, with the label `auto-report`). **These issues are public: anyone can read them.** This is **off by default** and can be set only by admin profiles under Settings → Error reports:

- **Off:** nothing is collected or sent.
- **Ask me first:** errors wait in the settings. With "Show what would be sent" you see the whole report and send it or discard it ("Dismiss"). After the start, a notice points out when reports are waiting.
- **Send automatically:** Sunak sends every new error immediately, without you seeing it first (when you switch this on, Sunak asks once more because the reports are public). This works only if a token is stored; without a token the reports wait as with "Ask me first".

**What is in the report:** Sunak version, operating system, Python version, kind of error and shortened error text, the stack trace (Sunak's files and functions with their code lines, no variable values) and the last 30 log lines. **Never:** chats, prompts, answers, contents of mails or files, API keys, passwords or the token. Because the issues are public, redaction is strict: private paths and file names (`<path>`), user and computer name, addresses of servers in the home network or on the internet other than well-known ones like github.com (`<host>`), IP and MAC addresses, email addresses and long texts in quotation marks that might come from a chat or document (`<text>`). If you want to be sure, use "Ask me first" and read every report before sending.

**The token (for whoever owns the repository):** On GitHub create, under Settings → Developer settings → Personal access tokens → Fine-grained tokens, a token that has access to **only this repository** and only the permission "Issues: Read and write", and store it under "Save token". It stays on your computer (only in the database, never in the log, the backup or the browser). "Check access" tests whether it works. Only the repository's owner or a collaborator can write such a token; whoever just uses the project reports errors with **"Open on GitHub"**: this opens a pre-filled issue in the browser that they submit with their own GitHub account (a classic token with `public_repo` would work too, but is too powerful and is not recommended). With your own fork the target can be changed via `SUNAK_REPORT_REPO`.

**Who needs a GitHub account?** Only whoever sends reports: the owner with their token (then other profiles and devices of the same installation report without an account of their own, because the token lives only on the server) or anyone who uses "Open on GitHub". Shipping a token inside the program would not be safe, so there is no collection service without an account.

**Duplicates and volume:** Every error has a fingerprint (kind of error plus the functions involved, without line numbers). If there is already an open issue for it, it only gets a short comment ("Seen again", at most one per day); an already closed issue is not reopened, instead a new one is created that points to it. At most three new issues are created per hour. "Create a sample report" creates a harmless example report with which you can try the preview and sending.

### Phone and tablet

1. Settings → Security: set a password (phone access does not work without a password).
2. Settings → Phone & tablet → switch on "Allow phones and tablets in my network".
3. Scan the QR code with the phone camera (or type in the address shown). Phone and computer must be on the same Wi-Fi and the computer must stay on; if the firewall asks, allow Python.
4. For an app icon choose "Add to Home Screen" in the browser menu.

The setting survives a restart. If you start Sunak with `--host 0.0.0.0`, it is reachable on the network anyway; then the page only shows address and code. Over `http://` on Wi-Fi the microphone does not work (browsers require https for it). If you access it through your own domain name (for example behind a reverse proxy), enter it in `SUNAK_ALLOWED_HOSTS`, see [Configuration](#configuration).

### Themes and language

- **Themes:** Sunak Dark and Sunak Light (pink), Retro (green terminal with monospace font), Cyberpunk (neon), Ocean, Forest, Sunset (light and warm) and 80s Corporate (beige office tech, navy title bar, burgundy, angular buttons with a 3D edge). Switch with the palette button at the top right or with a preview in Settings → Look, plus custom accent colors. All themes are checked for good readability. The theme applies per profile.
- **Language:** Settings → Look → Language. "Automatic" follows the browser's language; the page reloads afterwards. The chat model answers in the interface language too (unless you ask for another one in a message). Further languages can be added as a single file (see [Architecture](docs/ARCHITECTURE.md#languages)).
- **App:** Sunak can be installed as a web app (PWA) where the browser allows it (on `localhost` or with https).

## Commands (`sunak -h`)

`sunak -h` shows all commands and start options in groups, each with an example; `sunak <command> -h` (or `sunak help <command>`) shows the details of a command. For typos, Sunak suggests the matching command. Colors can be switched off with `NO_COLOR=1`.

| Command | Purpose |
|---|---|
| `sunak` | Start Sunak and open it in the browser (if it is already running, only the browser is opened) |
| `sunak status` | Is Sunak running? Address and autostart |
| `sunak stop` | Stop the running Sunak |
| `sunak update` | Shows the changes (changelog), asks, then installs the newest version and stops a running Sunak (then start `sunak`); `--yes` does not ask |
| `sunak changelog` | What the next update changes, without installing anything |
| `sunak import FILE` | Add a backup or an exported chat to a profile (`--profile ID`, default the main profile; `--data-dir PATH` for another data folder), see "Restore a backup" above |
| `sunak version` | Installed version (also `sunak --version`, and at the bottom of Settings) |
| `sunak gpu` | Which graphics card Ollama can use |
| `sunak desktop [install\|update\|uninstall\|status]` | The optional [desktop app](#desktop-app-optional): download and install the finished package, renew it, remove it, or show the state |
| `sunak logs [LINES]` | Where the log file is, and its last lines (default 40; `--data-dir PATH` for another data folder) |
| `sunak mail-selftest` | Test a real mail account from start to end, see [Mail](#mail) |
| `sunak autostart on\|off\|status` | Start Sunak in the background when you log in |
| `sunak shortcut` | Create the desktop icon again |
| `sunak uninstall` | Remove Sunak, asks before deleting data |
| `sunak help <command>` | Details of a command |

**Start options:** `--port N` (first port Sunak tries; default 7000, if it is busy Sunak counts up through nine more ports), `--host ADDRESS` (default `127.0.0.1`; `0.0.0.0` for access from the network, then be sure to set a password), `--data-dir PATH` (data folder, default `~/.sunak`), `--no-browser`, `--version`. `status` and `stop` look on the port and the nine after it (`--port N` chooses another starting point).

## Configuration

You set everything important in the interface (Settings). Optionally via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `SUNAK_PORT` | `7000` | Port (if it is busy, the next free one is taken) |
| `SUNAK_HOST` | `127.0.0.1` | `0.0.0.0` for access from the network |
| `SUNAK_DATA` | `~/.sunak` | Folder for the database (Windows: `C:\Users\<name>\.sunak`) |
| `SUNAK_PASSWORD` | – | Set a password at startup |
| `SUNAK_NO_BROWSER` | – | Set to any value: do not open the browser |
| `SUNAK_DEBUG` | – | Set to any value: more detailed log (level DEBUG: also every read request, background pages and queries). Never contents of chats, prompts or keys |
| `SUNAK_REPORT_REPO` | `M4XM77R/Sunak` | GitHub repository (`owner/name`) where error reports land as issues, for example for your own fork |
| `SUNAK_MODEL_SLOTS` | `1` | How many requests a local model (Ollama on this computer or on the LAN) handles at the same time; further ones wait in the queue. Models on the internet (Claude, OpenAI) take four at a time |
| `SUNAK_ALLOWED_HOSTS` | – | Further host names under which Sunak is reachable, comma-separated (`*` for all). Otherwise `localhost`, IP addresses, names without a dot and `*.local` are allowed (protection against DNS rebinding) |
| `SUNAK_GPU` | – | Docker only: `nvidia` or `amd`, so that the CPU warning works there too (the GPU Compose files set it themselves) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama address on the first start |
| `ANTHROPIC_API_KEY` | – | Sets up Claude as a provider automatically on the first start |
| `SUNAK_ALLOW_PRIVATE_FETCH` | – | `1` lets web search and Research also read pages from the local network (normally refused, see Models, GPU and search) |
| `SEARXNG_URL` | – | Your own SearXNG instance for web search and Research instead of DuckDuckGo |
| `NO_COLOR` | – | No colors in the terminal output |

**Log:** Sunak writes what it does to the terminal it was started from and to the file `~/.sunak/logs/sunak.log` (in the data folder, readable only by you). Every line has a time, a level and an area, for example `13:11:54 INFO    http     POST /api/chat 200 3.4s`. Logged are start and stop, requests that change something (method, path, status, duration; errors as WARNING or ERROR), the queue ("busy, the request waits"), image jobs, update checks and errors with their cause. **Never** in it: chats, prompts, answers, mails, file contents, passwords, API keys or query texts (not even with `SUNAK_DEBUG`). The file is limited to **50 MB**: five files (`sunak.log`, `sunak.log.1` to `.4`) of at most 10 MB each, the oldest is overwritten. `sunak logs` shows the location and the end of the file.

**Where is my data?** In `~/.sunak` (SQLite file `sunak.db`, pictures in `images/`, further profiles in `profiles/`), with Docker in the `data/` folder. The program itself is in `~/.sunak/app` on Linux and macOS, and in `%LOCALAPPDATA%\sunak\app` on Windows.

### Installer options

| | macOS / Linux (`install.sh`) | Windows (`install.ps1`, set as an environment variable to `"1"` beforehand) |
|---|---|---|
| No questions, everything yes | `--yes` | `$env:SUNAK_YES = "1"` |
| Do not install Ollama | `--no-ollama` | `$env:SUNAK_NO_OLLAMA = "1"` |
| Do not start Sunak after installing | `--no-start` | `$env:SUNAK_NO_START = "1"` |
| No desktop icon | `--no-shortcut` | `$env:SUNAK_NO_SHORTCUT = "1"` |
| Switch autostart on without asking | `--autostart` | `$env:SUNAK_AUTOSTART = "1"` |
| Also install the [desktop app](#desktop-app-optional) (default: no) | `--desktop` or `SUNAK_DESKTOP=1` | `$env:SUNAK_DESKTOP = "1"` |

When piping, append options with `bash -s --`: `curl -fsSL …/install.sh | bash -s -- --yes --no-ollama`. With `SUNAK_HOME` (the installer's folder), `SUNAK_REPO` and `SUNAK_BRANCH` you can change the installation location or the source.

### Desktop app (optional)

If you prefer Sunak in its own window instead of the browser, there is a small Tauri app in [`desktop/`](desktop/README.md). The installer can fetch it (opt-in: asks at the end, default no, or `--desktop` / `SUNAK_DESKTOP=1`); it takes the finished package from the newest `desktop-v*` release and prints a hint if there is none yet. Already installed Sunak? Run `sunak desktop install` or press *Install desktop app* in Settings → Desktop app (admin profiles); after the update to 1.1.0 Sunak shows a one-time hint, and never installs anything on its own. `sunak update` renews an installed app as well when a newer desktop release exists (not while the app is open; then close it and run `sunak desktop update`); it never installs the app by itself. It needs an installed Sunak (it starts the server itself and stops it when the window closes), is built by the GitHub Actions workflow `desktop` for Windows, macOS and Linux, and is not code-signed. The normal installation does not change and needs no Rust.

## Updating and uninstalling

### Updating

- **In the app:** When new versions exist, "Update available" appears at the top left. A click on **Update** first shows the changes from the changelog; only **Install update** installs and restarts Sunak. Nothing is ever installed without a click.
- **In the terminal:** `sunak update` first shows the changes and asks "Install the update now? [y/N]" (`j` and `ja` work too). On yes it fetches the newest version and stops a running Sunak, so that the next start uses it. `sunak update --yes` (or `-y`) does not ask; without a terminal (scripts, autostart, the Update button) it never asks. To only look: `sunak changelog`. Without an installation (clone): `git pull`.
- **Check now:** Settings → Updates → "Check for updates now" looks immediately (even if the notice is switched off) and shows "up to date", "New version x.y.z available" or "Check failed" with the reason why the check did not work (no clone, no network, no upstream branch). If there is a new version, its changes appear below and "Install update" next to it.
- **Changelog:** [`CHANGELOG.md`](CHANGELOG.md) in the main folder, one section per version (`## [0.14.0] – 2026-10-07`, short points under Added, Changed, Fixed, Removed). During the update check, Sunak reads the file from the state on the remote (`git show`) and shows the sections between your version and the new one before anything is installed: in the app (Update button, Settings → Updates) and in the terminal. If the file is missing or broken, the update still works, with the note "No changelog available". Every change to Sunak gets a new version **and** an entry there.
- **Checking:** Sunak looks via `git fetch` at startup and then every 6 hours, quietly and without asking; without a network or a clone there is simply no notice. To switch it off: Settings → Updates → untick "Check for updates" → Save settings.
- The installer remembers the clone it installed from, and `sunak update` pulls there with `git pull`. For the public repository this needs no credentials (only for a private fork).
- **Version number:** `sunak version` (also shown at the bottom of Settings). The version has the form **a.b.c** (`sunak/__init__.py`) and goes up with every change: **c** for small fixes and documentation corrections (0.8.0 → 0.8.1), **b** for smaller updates such as new features (0.8.1 → 0.9.0, c becomes 0), **a** only for big updates, and the maintainer alone decides that. Sunak has been at **1.0** since 1.0.0 (the first stable release); a stays at 1 until the maintainer decides otherwise.

### Uninstalling

```bash
sunak uninstall
```

This removes the `sunak` command, the app folder, desktop and menu icons, autostart and the PATH entry. If Sunak is still running, it is stopped first. Sunak asks about everything else one by one, and the default (Enter) is always "keep":

1. Sunak's Docker container, if present,
2. **your data** (chats, settings, API keys, mail accounts in `~/.sunak`),
3. **Ollama itself** (installed natively or as a Docker container). Other programs may use it. On yes, Sunak removes it in the way that fits the system: on Windows via the Ollama uninstaller or winget, on macOS via Homebrew or the app, on Linux the service, program and user of the official installation (asks for the `sudo` password), Snap via `snap remove`. For a distribution package Sunak says that the package manager takes care of it,
4. the **downloaded models**. They take up a lot of space, but would be usable again immediately after reinstalling Ollama.

Without a terminal, none of this is deleted. Running it twice does no harm.

- Without questions: `sunak uninstall --yes` (program gone; data, Ollama and models stay). Individually on top: `--purge` (delete data), `--with-ollama` (uninstall Ollama), `--with-models` (delete models).
- As a one-liner, also when the `sunak` command is missing: `curl -fsSL https://raw.githubusercontent.com/M4XM77R/sunak/main/uninstall.sh | bash` (options: `| bash -s -- --yes`), on Windows `irm https://raw.githubusercontent.com/M4XM77R/sunak/main/uninstall.ps1 | iex` (options beforehand as `$env:SUNAK_YES = "1"`, `SUNAK_PURGE`, `SUNAK_WITH_OLLAMA`, `SUNAK_WITH_MODELS`). In a clone: `./uninstall.sh` or `.\uninstall.ps1`.
- If you installed Sunak before this version, first run `sunak update` or use the script; the old `sunak uninstall` command also deleted the data after one question.

## Troubleshooting

| Problem | Solution |
|---|---|
| The command `sunak` is not found | Open a new terminal window (the installer adds `~/.local/bin` to the PATH). As a last resort `python3 start.py` in the folder `~/.sunak/app` |
| "Ports 7000-7009 are all busy" | Choose another port: `sunak --port 8123` |
| The page says "This address is not allowed" | You access it through a host name that Sunak does not know: add it to `SUNAK_ALLOWED_HOSTS` |
| No models in the selector | Is Ollama running? Models → "Start Ollama" or "Install Ollama". Or enter a cloud provider under Settings → Providers |
| Answers are very slow | The model is probably running on the processor: `sunak gpu` and the Models page show it. Choose a smaller model |
| Research says the web search does not work | The message names the search engines and the reason (for example a robot check by DuckDuckGo). Check your internet connection or set `SEARXNG_URL` to your own SearXNG instance. The details are in `sunak logs` under "Research:" |
| A picture request in the chat is not painted | A hint names the reason: image generation is not set up yet (program or model missing). If there is no hint, `sunak logs` shows "Picture request check (chat/research)"; every check is listed there, also for normal messages |
| "Waiting in the queue: place n" | The model is busy with other requests; yours is served in order. **Stop** withdraws it |
| An error report cannot be sent ("GitHub refused the token") | The token needs "Issues: Read and write" for the repository `M4XM77R/Sunak` (or your `SUNAK_REPORT_REPO`) and must not have expired; "Check access" tests it. Without a token, "Open on GitHub" helps |
| The phone cannot reach Sunak | Password set? Same Wi-Fi? Firewall of the computer: allow Python |
| Mail login rejected | Use an app password instead of the normal password, enable IMAP at GMX/WEB.DE; Microsoft accounts often work only with OAuth, which Sunak cannot do |
| The microphone does nothing | It works only on `localhost` or with https, not through phone access |
| Sunak does not quit | `sunak stop`, or Settings → Stop Sunak |

## Development

All you need is Python 3.9+. There is nothing to install and no build step.

```bash
git clone https://github.com/M4XM77R/sunak.git && cd sunak
SUNAK_DATA=./data python3 -m sunak --no-browser   # start the server with its own data folder
python3 -m unittest discover tests -v             # tests with simulated backends (Ollama, Claude, OpenAI)
SUNAK_DEBUG=1 python3 -m sunak                    # with detailed log
```

Changes to `sunak/static/` become visible after a reload in the browser. Changes to Python files need a restart. The tests run in GitHub Actions on Linux, macOS and Windows.

| File | Contents |
|---|---|
| `sunak/__main__.py` | Command line: start, all commands, help (`COMMANDS`) |
| `sunak/server.py` | HTTP server, all API endpoints, settings, login, profiles |
| `sunak/providers.py` | Connection to Ollama, Claude (Anthropic API) and OpenAI-compatible APIs (streaming) |
| `sunak/ollama.py`, `gpu.py` | Ollama integration (catalog, status, start, installation) and GPU detection |
| `sunak/modelsearch.py` | Model search in the Ollama library and on Hugging Face |
| `sunak/mcp.py` | MCP client (stdio and Streamable HTTP) |
| `sunak/toolrun.py` | Tool loop in the chat: calls MCP tools per backend, approvals |
| `sunak/backup.py` | Importing a backup or an exported chat (`sunak import`, Settings → Data) |
| `sunak/mail.py`, `mailtest.py` | Mail (IMAP, SMTP) and `sunak mail-selftest` |
| `sunak/reminders.py` | Calendar reminders and push messages to ntfy |
| `sunak/cal.py` | Calendar (iCalendar, CalDAV, ICS subscriptions) |
| `sunak/research.py` | Web search and page analysis for Research and web search in the chat |
| `sunak/extract.py`, `knowledge.py` | Text from files (own PDF reader) and knowledge base (sections, full-text search) |
| `sunak/memory.py` | Automatic memory |
| `sunak/images.py`, `imagegen.py`, `sdcpp.py` | Pictures in the chat, image generation (Automatic1111, ComfyUI) and own image program |
| `sunak/speech.py`, `qr.py` | Whisper connection, QR code for phone access |
| `sunak/desktop.py`, `updates.py`, `changelog.py`, `uninstall.py` | Autostart and icons, update check and button, reading the changelog, uninstallation |
| `sunak/db.py` | SQLite storage |
| `desktop/` | Optional Tauri desktop app (Rust shell around the server), see `desktop/README.md` |
| `sunak/static/` | Interface (HTML, CSS, one JavaScript file, language files) |

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes the structure, data flow, all API endpoints, backends and extension points.

## License

MIT
