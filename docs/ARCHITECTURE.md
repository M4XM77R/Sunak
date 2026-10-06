# Architektur von Sunak

Sunak ist ein einzelner Python-Prozess. Er liefert die Weboberfläche aus, stellt eine JSON-API bereit und spricht mit den KI-Backends. Es gibt keine Python-Abhängigkeiten und keinen Build-Schritt für das Frontend.

```
Browser (sunak/static)  ──HTTP/JSON, NDJSON-Streams──▶  sunak/server.py
                                                          │
                     ┌────────────────────┬───────────────┼──────────────────┐
                     ▼                    ▼               ▼                  ▼
               sunak/db.py         sunak/providers.py  sunak/research.py   Dateisystem
               SQLite-Datei        Ollama / OpenAI-API  DuckDuckGo/SearXNG  (static/)
```

## Dateien

| Datei | Aufgabe |
|---|---|
| `sunak/__main__.py` | Kommandozeile (`python -m sunak`), sucht einen freien Port, startet den Server, öffnet den Browser |
| `sunak/server.py` | `App` (Zustand, Einstellungen, Modellauswahl, Login, Prompt-Aufbau) und `Handler` (HTTP-Routing, alle API-Endpunkte) |
| `sunak/db.py` | SQLite-Speicher: Chats, Nachrichten, Dokumente, Notizen, Einstellungen |
| `sunak/providers.py` | Backends: Ollama, Claude (Anthropic Messages API) und OpenAI-kompatible APIs, Streaming, Modell-Download |
| `sunak/ollama.py` | Native Ollama-Integration: Modellkatalog, Status, lokales Ollama finden, starten und installieren |
| `sunak/research.py` | Websuche, Seiten lesen, Prompt für den Recherchebericht |
| `sunak/extract.py` | Text aus hochgeladenen Dateien: PDF (eigener Leser), .docx, .odt, .pptx, HTML, Text |
| `sunak/knowledge.py` | Wissensbasis: Abschnitte bilden, suchen, passende Abschnitte für den Chat auswählen |
| `sunak/static/` | Oberfläche: `index.html`, `app.js` (gesamte Logik), `app.css`, `login.html`, Icon, PWA-Manifest |
| `tests/test_server.py` | End-to-End-Tests gegen simulierte Backends |
| `tests/test_extract.py` | Tests für Textauslese und Wissensbasis (die Testdateien werden im Test erzeugt) |
| `install.sh`, `install.ps1` | Installer für macOS/Linux und Windows |
| `Dockerfile`, `docker-compose*.yml` | Container mit Ollama, optional mit NVIDIA-GPU |

## Datenfluss einer Chat-Nachricht

1. `app.js` legt bei Bedarf einen Chat an (`POST /api/sessions`) und schickt die Nachricht an `POST /api/chat`.
2. `Handler.chat` speichert die Nachricht und löst die Modell-ID `provider::modell` über `App.resolve` auf.
3. `App.build_messages` setzt den Verlauf zusammen: Systemprompt aus den Einstellungen, Prompt des Chats, Notizen mit Markierung „memory“, bei eingeschalteter Wissensbasis die passenden Auszüge (siehe unten) und danach die bisherigen Nachrichten. Denkprozesse (`<think>…</think>`) werden dabei entfernt.
4. `providers.chat_stream` streamt die Antwort als Paare `("think" | "text", stück)`.
5. Der Server reicht jedes Stück sofort als NDJSON-Zeile an den Browser weiter, zum Beispiel `{"type": "text", "t": "Hallo"}`.
6. Am Ende wird die Antwort gespeichert. Der Denkprozess bleibt dabei in `<think>`-Tags eingebettet. Bricht die Verbindung ab, bleibt die Teilantwort erhalten.

„Neu generieren“ und „Bearbeiten“ schicken `truncate_from` mit. Der Server löscht dann diese Nachricht und alle späteren, bevor er antwortet.

## API

Alle Endpunkte liegen unter `/api/`. Schreibende Anfragen brauchen den Header `X-Requested-With: sunak`, das schützt vor CSRF. Ist ein Passwort gesetzt, ist außerdem das Cookie `sunak_token` nötig.

| Methode und Pfad | Zweck | Antwort |
|---|---|---|
| `GET /api/status` | Version, Login-Status, RAM, empfohlenes Modell | JSON |
| `POST /api/login`, `POST /api/logout` | Anmelden, Abmelden | JSON |
| `GET`/`PUT /api/settings` | Einstellungen und Provider | JSON |
| `GET /api/models` | Modelle aller Provider, dazu Fehler nicht erreichbarer Provider | JSON |
| `GET /api/ollama` | Ollama-Status (installiert, läuft, Version), installierte Modelle mit Größe, Katalog mit `fits`, Installationsweg | JSON |
| `POST /api/ollama/start` | Lokales Ollama im Hintergrund starten | JSON |
| `POST /api/ollama/install` | Ollama per winget bzw. Homebrew installieren | NDJSON `status` |
| `POST /api/models/pull` | Ollama-Modell herunterladen; Fortschritt aller Layer summiert | NDJSON `progress` (`completed`, `total` in Bytes) |
| `POST /api/models/delete` | Ollama-Modell löschen | JSON |
| `GET`/`POST /api/sessions`, `GET`/`PATCH`/`DELETE /api/sessions/<id>` | Chats | JSON |
| `POST /api/chat` | Antwort erzeugen; `use_kb` schaltet die Wissensbasis für den Chat ein oder aus | NDJSON `start`, `sources` (nur mit Wissensbasis), `think`, `text`, `done`/`error` |
| `POST /api/compare` | Ein Prompt an 2 bis 4 Modelle | NDJSON mit Modellindex `i` |
| `POST /api/research` | Web-Recherche mit Bericht | NDJSON `status`, `sources`, `text`, `done`/`error` |
| `GET`/`POST /api/documents`, `GET`/`PUT`/`DELETE /api/documents/<id>` | Dokumente | JSON |
| `POST /api/documents/ai` | KI-Bearbeitung eines Dokuments oder einer Markierung | NDJSON `text` |
| `GET`/`POST /api/notes`, `PATCH`/`DELETE /api/notes/<id>` | Notizen und Gedächtnis | JSON |
| `GET /api/knowledge` | Dateien der Wissensbasis, Gesamtgröße, ob FTS5 verfügbar ist | JSON |
| `POST /api/knowledge` | Datei hinzufügen: `{name, data}` mit `data` als Base64; gleicher Name ersetzt die alte Datei | JSON |
| `GET`/`DELETE /api/knowledge/<id>` | Datei mit ausgelesenem Text, Datei entfernen | JSON |
| `GET /api/knowledge/search?q=` | Volltextsuche mit Textausschnitt | JSON |
| `POST /api/extract` | Text einer Datei für einen Chat-Anhang (📎), gleiches Format wie oben | JSON |

Fehler kommen immer als `{"error": "…"}` mit HTTP-Status 4xx. Fehler, die erst während eines Streams auftreten, kommen als Event `{"type": "error"}`.

## Backends

Ein Provider ist ein Eintrag `{id, name, type, base_url, api_key}`, gespeichert in der Einstellung `providers`.

- **`ollama`** nutzt `/api/tags`, `/api/chat` (Streaming, Denkprozess im Feld `thinking`), `/api/pull` und `/api/delete`.
- **`anthropic`** (Claude) nutzt die Anthropic-API direkt per HTTP, ohne SDK, damit Sunak ohne Abhängigkeiten bleibt. `GET /v1/models` (seitenweise) liefert die Modelle; ist der Endpunkt nicht erreichbar, nimmt Sunak eine eingebaute Liste (`CLAUDE_FALLBACK_MODELS`), ein abgelehnter Key wird dagegen als Fehler angezeigt. Chats laufen über `POST /v1/messages` mit `stream: true`, und die Server-Sent Events werden in Text (`text_delta`) und Denkprozess (`thinking_delta`) zerlegt. Dabei gilt:
  - Der Systemprompt steht als eigenes Feld `system`; aufeinanderfolgende Nachrichten derselben Rolle werden zusammengefügt.
  - Modelle mit adaptivem Denken (Opus/Sonnet ab 4.6, Fable) bekommen `thinking: {type: "adaptive", display: "summarized"}`, damit der zusammengefasste Denkprozess sichtbar ist. Haiku und ältere Modelle bekommen kein `thinking`.
  - `temperature` wird nicht gesendet, weil aktuelle Claude-Modelle es ablehnen. `max_tokens` richtet sich nach dem Modell (`claude_max_tokens`).
  - Bei Claude Opus 5.5, Opus 5, Sonnet 5.5 und Fable 5.1 auf `api.anthropic.com` setzt Sunak `fallbacks: "default"` (Beta-Header `server-side-fallback-2026-07-01`). Lehnt ein Sicherheitsfilter eine Anfrage ab, beantwortet die API sie dann mit einem Ersatzmodell. Eine endgültige Ablehnung (`stop_reason: "refusal"`) erscheint als Fehlermeldung.
  - Der Key geht als `x-api-key` mit `anthropic-version: 2023-06-01` an die API.
- **`openai`** nutzt `/models` und `/chat/completions` mit Server-Sent Events. Denkprozesse kommen aus `reasoning_content` bzw. `reasoning`. Das funktioniert mit OpenAI, OpenRouter, Groq, LM Studio, llama.cpp und vLLM.

Lokale Adressen (localhost, private IPs, `*.local`, `host.docker.internal`) werden immer direkt angesprochen, also nie über einen System-Proxy.

Modell-IDs haben die Form `provider::modell`, zum Beispiel `ollama::qwen3:4b` oder `claude::claude-opus-5-5`.

**API-Keys** liegen nur in der lokalen Datenbank. `GET /api/settings` liefert statt des Keys nur `has_key`. Schickt der Browser beim Speichern ein leeres Key-Feld, bleibt der gespeicherte Key erhalten. Keys tauchen weder in Fehlermeldungen noch in Logs auf. Ist `ANTHROPIC_API_KEY` gesetzt, wird Claude beim ersten Start automatisch als Anbieter eingetragen.

## Native Ollama-Integration

Die Seite „Models“ und die Einrichtung beim ersten Start nutzen `sunak/ollama.py`:

- **Status**: `ollama.status` fragt `/api/version` und `/api/tags` des ersten Providers vom Typ `ollama` ab. Antwortet Ollama nicht, sucht Sunak die Programmdatei: `PATH`, Homebrew, `/Applications/Ollama.app`, `%LOCALAPPDATA%\Programs\Ollama`.
- **Starten**: Ist Ollama installiert, aber gestoppt, startet `ollama.start` es im Hintergrund. Auf macOS geschieht das über die App, sonst über `ollama serve` als losgelösten Prozess. Danach wartet Sunak bis zu 15 Sekunden auf eine Antwort. Das geht nur, wenn der Provider auf `localhost` zeigt.
- **Installieren**: Unter Windows nutzt Sunak `winget`, unter macOS Homebrew; beide brauchen kein Admin-Passwort. Die Ausgabe wird live gestreamt. Unter Linux braucht der offizielle Installer `sudo`, deshalb zeigt Sunak den Befehl zum Kopieren an. Ohne Homebrew gibt es einen Download-Link.
- **Katalog**: `CATALOG` ist eine kuratierte Liste mit Name, ungefährer Größe, Tags und Beschreibung. `fits()` markiert Modelle, die zum Arbeitsspeicher passen. Die Faustregel lautet: Größe × 1,3 + 2 GB.
- **Download**: `POST /api/models/pull` streamt `/api/pull` von Ollama und summiert den Fortschritt aller Layer. Bricht der Browser die Anfrage ab („Cancel“), schließt der Server die Verbindung zu Ollama und der Download stoppt. Bereits geladene Teile bleiben erhalten, ein neuer Start setzt dort fort.
- **Frontend**: Laufende Downloads liegen in `state.pulls` und laufen weiter, wenn man die Seite wechselt. Jedes Element mit `data-slot`/`data-pull` zeigt denselben Fortschritt, zum Beispiel Katalogkarte, Download-Liste und Einrichtungskarte im Chat.

## Deep Research

1. Das Modell schlägt bis zu drei Suchanfragen vor.
2. `research.search` sucht über DuckDuckGo, das ohne Schlüssel auskommt. Ist `SEARXNG_URL` gesetzt, wird stattdessen SearXNG verwendet.
3. Bis zu fünf Seiten werden geladen und in Text umgewandelt, jeweils höchstens 6000 Zeichen.
4. Das Modell schreibt einen Markdown-Bericht mit Quellenverweisen wie `[1]`.

## Wissensbasis

Hochgeladene Dateien gehen den Weg `extract.extract_text` → `knowledge.chunk` → `DB.kb_add`.

- **Textauslese** nur mit der Standardbibliothek. Word, OpenDocument und PowerPoint sind ZIP-Archive mit XML und werden mit `zipfile` und `ElementTree` gelesen. Für PDF gibt es einen eigenen kleinen Leser: Er findet alle Objekte (auch in Objekt-Streams von PDF 1.5+), entpackt Flate-, ASCII85- und ASCIIHex-Streams, folgt dem Seitenbaum mit geerbten Ressourcen und übersetzt Zeichen über die `ToUnicode`-CMap des Fonts, sonst über WinAnsi bzw. MacRoman. Leerzeichen und Zeilenumbrüche ergeben sich aus den Textpositionen. Formular-XObjects werden mitgelesen.
- **Grenzen:** Gescannte PDFs ohne Textebene (das bräuchte Texterkennung) und verschlüsselte PDFs liefern eine verständliche Fehlermeldung. Bei Fonts ohne `ToUnicode`, die nur Glyph-Nummern enthalten, bleibt der Text leer. Mehrspaltige Layouts werden in der Reihenfolge des Content-Streams gelesen.
- **Abschnitte** von etwa 1000 Zeichen an Absatz-, Zeilen- oder Satzgrenzen.
- **Suche:** SQLite-FTS5 (`kb_fts`, Rowid = `kb_chunks.id`, Umlaute und Akzente werden beim Vergleich ignoriert) mit bm25-Ranking. Die Suchwörter stammen aus den letzten beiden Fragen ohne Stoppwörter (deutsch und englisch), Wörter ab 4 Buchstaben auch als Präfix, damit „Handbuch“ auch „Handbuchs“ findet. Fehlt FTS5 im SQLite, rechnet `knowledge._scan` ein einfaches TF-IDF in Python.
- **Prompt:** Ist die ganze Wissensbasis höchstens 8000 Zeichen groß, bekommt das Modell alles (dann klappen auch Fragen wie „fasse das zusammen“). Sonst bekommt es bis zu 6 passende Abschnitte mit höchstens 7000 Zeichen. Die Abschnitte stehen mit Dateinamen im Systemprompt, und das Modell soll die Datei in eckigen Klammern nennen.
- **Quellen:** Die verwendeten Dateien werden als `sources`-Ereignis gesendet und in `messages.meta` gespeichert, damit sie auch später unter der Antwort stehen.

## Datenhaltung

Alle Daten liegen in einer SQLite-Datei: `~/.sunak/sunak.db`, der Ordner lässt sich über `SUNAK_DATA` ändern.

| Tabelle | Inhalt |
|---|---|
| `sessions` | Chats: Titel, Modell, eigener Systemprompt, `use_kb` (Wissensbasis an/aus) |
| `messages` | Nachrichten der Chats (werden mit dem Chat gelöscht); `meta` (JSON) enthält z. B. die Quellen |
| `kb_files`, `kb_chunks`, `kb_fts` | Wissensbasis: Dateien, ihre Textabschnitte und der Volltextindex |
| `documents` | Markdown-Dokumente |
| `notes` | Notizen; `is_memory = 1` bedeutet „im Gedächtnis“ |
| `settings` | Schlüssel-Wert-Paare als JSON: `prefs`, `providers`, `password_hash`, `secret` |

Spalten, die später dazukamen, legt `DB.__init__` beim Start an (`MIGRATIONS`), ältere Datenbanken funktionieren also weiter. Die hochgeladenen Originaldateien werden nicht aufbewahrt, nur ihr Text.

Passwörter werden mit PBKDF2-SHA256 und Salt gespeichert. Das Login-Cookie ist ein HMAC aus dem Geheimnis der Installation und dem Passwort-Hash. Wird das Passwort geändert, sind daher alle Sitzungen abgemeldet.

## Frontend

`app.js` ist eine einzige Datei ohne Framework und gliedert sich in Abschnitte: API-Helfer, Markdown-Renderer, Theme, Navigation, Modelle, Chats, Senden, Modell-Download, Compare, Research, Dokumente, Notizen, Einstellungen und Start.

- Der Markdown-Renderer maskiert zuerst alles HTML und baut dann nur bekannte Elemente auf. Modellausgaben können daher kein Skript einschleusen.
- Streams werden mit `fetch` und einem `ReadableStream` zeilenweise gelesen und pro Animationsframe neu gezeichnet.
- Theme und Akzentfarbe liegen in CSS-Variablen (`--accent`, Standard `#ff4fa3`). Gespeichert werden sie in den Einstellungen und zusätzlich in `localStorage`, damit auch die Login-Seite passend aussieht.

## Konfiguration

Umgebungsvariablen: `SUNAK_HOST`, `SUNAK_PORT`, `SUNAK_DATA`, `SUNAK_PASSWORD`, `SUNAK_NO_BROWSER`, `SUNAK_DEBUG` (Zugriffslog), `OLLAMA_BASE_URL`, `SEARXNG_URL`. Alles Weitere wird in der Oberfläche eingestellt und in der Datenbank gespeichert.

## Tests

```bash
python3 -m unittest discover tests -v
```

Die Tests starten Sunak und einen simulierten Server, der die Ollama-, Anthropic- und OpenAI-API nachbildet. Abgedeckt sind Chat, Wissensbasis (Hochladen, Suche, Auszüge im Prompt, Quellen), Textauslese aus PDF, Word, OpenDocument und PowerPoint, Datenbank-Migration, Neu generieren, Denkprozess, Gedächtnis, Compare, Research (mit gestubbter Suche), Dokumente, Modell-Download mit Fortschritt, Ollama-Status und Katalog, Claude (Streaming, Header, Denkprozess, Ablehnung, falscher Key, Key-Maskierung), Login, CSRF-Schutz und Pfad-Traversal. GitHub Actions führt sie auf Linux, macOS und Windows aus (`.github/workflows/test.yml`).

## Erweitern

- **Neuer API-Endpunkt:** Methode auf `Handler` schreiben und in `ROUTES` eintragen; Ausnahmen vom Typ `ValueError` werden automatisch als 400 beantwortet.
- **Neues Modell im Katalog:** Eintrag in `CATALOG` in `sunak/ollama.py` ergänzen (Ollama-Name, Titel, Größe in GB, Tags, Beschreibung).
- **Neuer Backend-Typ:** `list_models` und `chat_stream` in `providers.py` um den Typ erweitern und den Typ in `App.save_settings` zulassen.
- **Neue Ansicht:** einen `<section class="view" id="view-…">` und einen Navigationsknopf in `index.html` anlegen, die Logik als eigenen Abschnitt in `app.js` ergänzen und in `show()` einhängen.
