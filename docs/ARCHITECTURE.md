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
| `sunak/providers.py` | Backends: Ollama und OpenAI-kompatible APIs, Streaming, Modell-Download |
| `sunak/research.py` | Websuche, Seiten lesen, Prompt für den Recherchebericht |
| `sunak/static/` | Oberfläche: `index.html`, `app.js` (gesamte Logik), `app.css`, `login.html`, Icon, PWA-Manifest |
| `tests/test_server.py` | End-to-End-Tests gegen simulierte Backends |
| `install.sh`, `install.ps1` | Installer für macOS/Linux und Windows |
| `Dockerfile`, `docker-compose*.yml` | Container mit Ollama, optional mit NVIDIA-GPU |

## Datenfluss einer Chat-Nachricht

1. `app.js` legt bei Bedarf einen Chat an (`POST /api/sessions`) und schickt die Nachricht an `POST /api/chat`.
2. `Handler.chat` speichert die Nachricht und löst die Modell-ID `provider::modell` über `App.resolve` auf.
3. `App.build_messages` setzt den Verlauf zusammen: Systemprompt aus den Einstellungen, Prompt des Chats, Notizen mit Markierung „memory“ und danach die bisherigen Nachrichten. Denkprozesse (`<think>…</think>`) werden dabei entfernt.
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
| `POST /api/models/pull` | Ollama-Modell herunterladen | NDJSON `progress` |
| `POST /api/models/delete` | Ollama-Modell löschen | JSON |
| `GET`/`POST /api/sessions`, `GET`/`PATCH`/`DELETE /api/sessions/<id>` | Chats | JSON |
| `POST /api/chat` | Antwort erzeugen | NDJSON `start`, `think`, `text`, `done`/`error` |
| `POST /api/compare` | Ein Prompt an 2 bis 4 Modelle | NDJSON mit Modellindex `i` |
| `POST /api/research` | Web-Recherche mit Bericht | NDJSON `status`, `sources`, `text`, `done`/`error` |
| `GET`/`POST /api/documents`, `GET`/`PUT`/`DELETE /api/documents/<id>` | Dokumente | JSON |
| `POST /api/documents/ai` | KI-Bearbeitung eines Dokuments oder einer Markierung | NDJSON `text` |
| `GET`/`POST /api/notes`, `PATCH`/`DELETE /api/notes/<id>` | Notizen und Gedächtnis | JSON |

Fehler kommen immer als `{"error": "…"}` mit HTTP-Status 4xx. Fehler, die erst während eines Streams auftreten, kommen als Event `{"type": "error"}`.

## Backends

Ein Provider ist ein Eintrag `{id, name, type, base_url, api_key}`, gespeichert in der Einstellung `providers`.

- **`ollama`** nutzt `/api/tags`, `/api/chat` (Streaming, Denkprozess im Feld `thinking`), `/api/pull` und `/api/delete`.
- **`openai`** nutzt `/models` und `/chat/completions` mit Server-Sent Events. Denkprozesse kommen aus `reasoning_content` bzw. `reasoning`. Das funktioniert mit OpenAI, OpenRouter, Groq, LM Studio, llama.cpp und vLLM.

Lokale Adressen (localhost, private IPs, `*.local`, `host.docker.internal`) werden immer direkt angesprochen, also nie über einen System-Proxy.

Modell-IDs haben die Form `provider::modell`, zum Beispiel `ollama::qwen3:4b`.

## Deep Research

1. Das Modell schlägt bis zu drei Suchanfragen vor.
2. `research.search` sucht über DuckDuckGo, das ohne Schlüssel auskommt. Ist `SEARXNG_URL` gesetzt, wird stattdessen SearXNG verwendet.
3. Bis zu fünf Seiten werden geladen und in Text umgewandelt, jeweils höchstens 6000 Zeichen.
4. Das Modell schreibt einen Markdown-Bericht mit Quellenverweisen wie `[1]`.

## Datenhaltung

Alle Daten liegen in einer SQLite-Datei: `~/.sunak/sunak.db`, der Ordner lässt sich über `SUNAK_DATA` ändern.

| Tabelle | Inhalt |
|---|---|
| `sessions` | Chats: Titel, Modell, eigener Systemprompt |
| `messages` | Nachrichten der Chats (werden mit dem Chat gelöscht) |
| `documents` | Markdown-Dokumente |
| `notes` | Notizen; `is_memory = 1` bedeutet „im Gedächtnis“ |
| `settings` | Schlüssel-Wert-Paare als JSON: `prefs`, `providers`, `password_hash`, `secret` |

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

Die Tests starten Sunak und einen simulierten Server, der die Ollama- und OpenAI-API nachbildet. Abgedeckt sind Chat, Neu generieren, Denkprozess, Gedächtnis, Compare, Research (mit gestubbter Suche), Dokumente, Modell-Download, Login, CSRF-Schutz und Pfad-Traversal. GitHub Actions führt sie auf Linux, macOS und Windows aus (`.github/workflows/test.yml`).

## Erweitern

- **Neuer API-Endpunkt:** Methode auf `Handler` schreiben und in `ROUTES` eintragen; Ausnahmen vom Typ `ValueError` werden automatisch als 400 beantwortet.
- **Neuer Backend-Typ:** `list_models` und `chat_stream` in `providers.py` um den Typ erweitern und den Typ in `App.save_settings` zulassen.
- **Neue Ansicht:** einen `<section class="view" id="view-…">` und einen Navigationsknopf in `index.html` anlegen, die Logik als eigenen Abschnitt in `app.js` ergänzen und in `show()` einhängen.
