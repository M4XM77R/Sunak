<p align="center">
  <img src="sunak/static/icon.svg" width="72" alt="">
</p>
<h1 align="center">Sunak</h1>
<p align="center">
  Dein privater KI-Arbeitsplatz: Chat, Modellvergleich, Web-Recherche, Dokumente und Gedächtnis.<br>
  Läuft komplett auf deinem Rechner, in Pink und mit Fokus auf einfache Installation.
</p>

<p align="center"><img src="docs/chat.png" alt="Chat" width="820"></p>

## Installation (eine Zeile)

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/M4XM77R/sunak/main/install.sh | bash
```

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/M4XM77R/sunak/main/install.ps1 | iex
```

Der Installer

1. prüft Python 3.9+ und installiert es bei Bedarf,
2. legt den Befehl `sunak` an,
3. legt ein Sunak-Icon auf den Desktop (Linux zusätzlich ins App-Menü, macOS als `Sunak.app` in `~/Applications`, Windows zusätzlich ins Startmenü). Das Icon startet Sunak ohne Terminalfenster oder öffnet es, wenn es schon läuft,
4. fragt, ob Sunak beim Anmelden automatisch im Hintergrund starten soll (Standard: nein),
5. bietet an, [Ollama](https://ollama.com) für lokale Modelle zu installieren,
6. startet Sunak und öffnet den Browser auf `http://localhost:7000`.

Beim ersten Start erkennt Sunak deinen Arbeitsspeicher und schlägt ein passendes Modell vor. Ein Klick lädt es herunter, danach kannst du sofort chatten.

> **Privates Repository?** Die Ein-Zeilen-Befehle funktionieren nur, solange das Repo öffentlich ist. Bei einem privaten Repo:
> `git clone https://github.com/M4XM77R/sunak.git && cd sunak && ./install.sh` (Windows: `.\install.ps1`).

### Ohne Installation ausprobieren

Sunak braucht **keine einzige Python-Abhängigkeit**. Klonen und starten reicht:

```bash
git clone https://github.com/M4XM77R/sunak.git
cd sunak
python3 start.py
```

Unter Windows reicht ein Doppelklick auf `start.py`.

### Docker (inklusive Ollama)

```bash
docker compose up -d                      # http://localhost:7000
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d   # mit NVIDIA-GPU
```

## Funktionen

| | |
|---|---|
| 💬 **Chat** | Streaming-Antworten, Volltextsuche über alle Chats, Export als Markdown, JSON oder PDF, Bearbeiten und Neu generieren, Markdown, Tabellen, Code mit Kopier-Knopf, Denkprozess von Reasoning-Modellen ein- und ausklappbar, Dateien anhängen (auch PDF, Word, PowerPoint) per 📎 oder Drag & Drop |
| 🤖 **Claude** | Claude als eigener Anbieter: API-Key eintragen, die verfügbaren Claude-Modelle erscheinen automatisch in der Auswahl. Antworten werden gestreamt, der Denkprozess ist zusammengefasst sichtbar. Funktioniert in Chat, Compare, Research und Documents |
| 📚 **Knowledge** | Eigene Wissensbasis: PDFs, Word (.docx), OpenDocument (.odt), PowerPoint (.pptx), HTML, Markdown, Text, CSV und Code hochladen, im Chat mit 📚 einschalten und Fragen dazu stellen. Antworten zeigen, aus welchen Dateien sie stammen. Volltextsuche über alle Dateien. Alles bleibt lokal, ohne Zusatzsoftware |
| 🎭 **Personas** | Eigene Systemprompts als Personas, oben im Chat umschaltbar. Mitgeliefert: Assistant, Coder, Writer, Translator, Teacher; alle änderbar, eigene hinzufügbar (Settings → Personas) |
| ⚖️ **Compare** | Ein Prompt an 2 bis 4 Modelle gleichzeitig, Antworten und Geschwindigkeit nebeneinander |
| 🔎 **Research** | Sucht im Web, liest die besten Seiten und schreibt einen Bericht mit Quellenangaben; als Dokument speicherbar |
| 📝 **Documents** | Markdown-Editor mit Autosave, Vorschau, Export und KI-Bearbeitung („kürzer“, „Grammatik korrigieren“), auch nur für markierten Text, mit Rückgängig |
| 🧠 **Notes & Memory** | Notizen; als „memory“ markierte Notizen kennt die KI in jedem Chat |
| 🧩 **Modelle** | Eingebaute Ollama-Verwaltung: Modellkatalog mit Empfehlungen passend zu deinem RAM, Download per Klick mit Fortschrittsbalken und Abbrechen, jedes Ollama-Modell per Name, installierte Modelle anzeigen und löschen. Ollama lässt sich aus Sunak heraus starten und unter Windows (winget) und macOS (Homebrew) auch installieren. Zusätzlich jede OpenAI-kompatible API: OpenAI, OpenRouter, Groq, LM Studio, llama.cpp, vLLM |
| 🎨 **Look** | Dunkel/Hell, Pink als Standard-Akzent, weitere Akzentfarben in den Einstellungen, als App installierbar (PWA), handytauglich |
| 🔒 **Sicherheit** | Läuft standardmäßig nur auf `localhost`; optionales Passwort; Daten in einer SQLite-Datei unter `~/.sunak` |

<p align="center"><img src="docs/models.png" alt="Modelle" width="820"></p>
<p align="center"><img src="docs/onboarding.png" alt="Erster Start" width="410"> <img src="docs/compare.png" alt="Compare" width="410"></p>

## Bedienung

| Aktion | So geht's |
|---|---|
| Senden / neue Zeile | `Enter` / `Shift+Enter` |
| Neuer Chat | `Strg+K` (Mac: `⌘K`) |
| Modell herunterladen | 🧩 Models → Modell aussuchen → Download (Abbrechen jederzeit möglich, der Download läuft beim nächsten Mal weiter) |
| Modell wechseln | Auswahl oben rechts |
| Persona wechseln | Auswahl oben neben dem Modell, gilt für den aktuellen Chat. Eigene Personas: Settings → Personas |
| Alte Chats finden | Suchfeld über der Chatliste: durchsucht Titel und alle Nachrichten, ein Klick springt zur Stelle |
| Chat exportieren | ⬇ oben rechts → Markdown, JSON oder Drucken/PDF |
| Alles sichern | Settings → Data → Download backup (ohne API-Keys und Passwort) |
| Fragen zu eigenen Dateien | 📚 Knowledge → Dateien hineinziehen → im Chat 📚 neben dem Eingabefeld einschalten. Für eine einzelne Datei reicht auch 📎 |
| Claude nutzen | Settings → Providers → Preset „Claude (Anthropic)“ → API-Key von [console.anthropic.com](https://console.anthropic.com) einfügen → Save settings. Alternativ beim ersten Start „Use Claude with an API key“ klicken |
| Anderes Cloud-Modell nutzen | Settings → Providers → Preset wählen → API-Key eintragen → Save settings |
| Vom Handy nutzen | `sunak --host 0.0.0.0`, in Settings ein Passwort setzen, dann `http://<PC-IP>:7000` öffnen |
| Sunak beenden | Settings → ⏻ Stop Sunak, oder `sunak stop` |
| Läuft Sunak? | `sunak status` |
| Automatisch beim Anmelden starten | `sunak autostart on` (aus: `sunak autostart off`) |
| Desktop-Icon neu anlegen | `sunak shortcut` |
| Aktualisieren | `sunak update` (holt die neueste Version und beendet ein laufendes Sunak, damit der nächste Start sie nutzt) |
| Version anzeigen | `sunak version` |
| Deinstallieren | `sunak uninstall` (macOS/Linux, entfernt auch Icons und Autostart). Windows: `sunak autostart off`, dann den Ordner `%LOCALAPPDATA%\sunak` und die Sunak-Icons löschen |

## Konfiguration

Alles lässt sich in der Oberfläche einstellen. Optional per Umgebungsvariable:

| Variable | Standard | Zweck |
|---|---|---|
| `SUNAK_PORT` | `7000` | Port (ist er belegt, wird der nächste freie genommen) |
| `SUNAK_HOST` | `127.0.0.1` | `0.0.0.0` für Zugriff aus dem Netzwerk |
| `SUNAK_DATA` | `~/.sunak` | Ordner für die Datenbank |
| `SUNAK_PASSWORD` | – | Passwort beim Start setzen |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama-Adresse beim ersten Start |
| `ANTHROPIC_API_KEY` | – | Richtet beim ersten Start automatisch Claude als Anbieter ein |
| `SEARXNG_URL` | – | eigene SearXNG-Instanz für Research statt DuckDuckGo |

## Entwickeln

Voraussetzung ist nur Python 3.9+. Es gibt nichts zu installieren und keinen Build-Schritt.

```bash
git clone https://github.com/M4XM77R/sunak.git && cd sunak
SUNAK_DATA=./data python3 -m sunak --no-browser   # Server mit eigenem Datenordner starten
python3 -m unittest discover tests -v             # Tests mit simulierten Ollama- und OpenAI-Backends
SUNAK_DEBUG=1 python3 -m sunak                    # mit Zugriffslog
```

Änderungen an `sunak/static/` sind nach einem Neuladen im Browser sichtbar. Änderungen an Python-Dateien brauchen einen Neustart.

| Datei | Inhalt |
|---|---|
| `sunak/__main__.py` | Kommandozeile: Start, `stop`, `status`, `autostart`, `shortcut`, `version` |
| `sunak/server.py` | HTTP-Server, alle API-Endpunkte, Einstellungen, Login |
| `sunak/desktop.py` | Autostart, Desktop-Icon, laufendes Sunak finden und beenden |
| `sunak/providers.py` | Anbindung von Ollama, Claude (Anthropic API) und OpenAI-kompatiblen APIs (Streaming) |
| `sunak/ollama.py` | Ollama-Integration: Modellkatalog, Status, Ollama starten und installieren |
| `sunak/research.py` | Websuche und Seitenauswertung für Research |
| `sunak/extract.py` | Text aus PDF, Word, OpenDocument, PowerPoint, HTML und Textdateien (eigener kleiner PDF-Leser) |
| `sunak/knowledge.py` | Wissensbasis: Zerlegen in Abschnitte, Volltextsuche, Auswahl der passenden Abschnitte für den Chat |
| `sunak/db.py` | SQLite-Speicher |
| `sunak/static/` | Oberfläche (HTML, CSS, ein JavaScript-File) |

Aufbau, Datenfluss, alle API-Endpunkte, Backends und Erweiterungspunkte beschreibt [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Lizenz

MIT
