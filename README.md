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
2. legt den Befehl `sunak` an (unter Windows zusätzlich Desktop- und Startmenü-Verknüpfung),
3. bietet an, [Ollama](https://ollama.com) für lokale Modelle zu installieren,
4. startet Sunak und öffnet den Browser auf `http://localhost:7000`.

Beim ersten Start erkennt Sunak deinen Arbeitsspeicher und schlägt ein passendes Modell vor. Ein Klick lädt es herunter, danach kannst du sofort chatten.

> **Privates Repository?** Die Ein-Zeilen-Befehle funktionieren nur, solange das Repo öffentlich ist. Bei einem privaten Repo:
> `git clone https://github.com/M4XM77R/sunak.git && cd sunak && ./install.sh` (Windows: `.\install.ps1`).

### Ohne Installation ausprobieren

Sunak braucht **keine einzige Python-Abhängigkeit**. Klonen und starten reicht:

```bash
git clone https://github.com/M4XM77R/sunak.git
cd sunak
python3 -m sunak
```

### Docker (inklusive Ollama)

```bash
docker compose up -d                      # http://localhost:7000
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d   # mit NVIDIA-GPU
```

## Funktionen

| | |
|---|---|
| 💬 **Chat** | Streaming-Antworten, Verlauf mit Suche, Bearbeiten und Neu generieren, Markdown, Tabellen, Code mit Kopier-Knopf, Denkprozess von Reasoning-Modellen ein- und ausklappbar, Textdateien anhängen |
| ⚖️ **Compare** | Ein Prompt an 2 bis 4 Modelle gleichzeitig, Antworten und Geschwindigkeit nebeneinander |
| 🔎 **Research** | Sucht im Web, liest die besten Seiten und schreibt einen Bericht mit Quellenangaben; als Dokument speicherbar |
| 📝 **Documents** | Markdown-Editor mit Autosave, Vorschau, Export und KI-Bearbeitung („kürzer“, „Grammatik korrigieren“), auch nur für markierten Text, mit Rückgängig |
| 🧠 **Notes & Memory** | Notizen; als „memory“ markierte Notizen kennt die KI in jedem Chat |
| 🧩 **Modelle** | Ollama (lokal oder im Netzwerk) und jede OpenAI-kompatible API: OpenAI, OpenRouter, Groq, LM Studio, llama.cpp, vLLM. Modelle direkt in der Oberfläche herunterladen und löschen |
| 🎨 **Look** | Dunkel/Hell, Pink als Standard-Akzent, weitere Akzentfarben in den Einstellungen, als App installierbar (PWA), handytauglich |
| 🔒 **Sicherheit** | Läuft standardmäßig nur auf `localhost`; optionales Passwort; Daten in einer SQLite-Datei unter `~/.sunak` |

<p align="center"><img src="docs/onboarding.png" alt="Erster Start" width="410"> <img src="docs/compare.png" alt="Compare" width="410"></p>

## Bedienung

| Aktion | So geht's |
|---|---|
| Senden / neue Zeile | `Enter` / `Shift+Enter` |
| Neuer Chat | `Strg+K` (Mac: `⌘K`) |
| Modell wechseln | Auswahl oben rechts |
| Cloud-Modell nutzen | Settings → Providers → Preset wählen → API-Key eintragen → Save |
| Vom Handy nutzen | `sunak --host 0.0.0.0`, in Settings ein Passwort setzen, dann `http://<PC-IP>:7000` öffnen |
| Aktualisieren | `sunak update` |
| Deinstallieren | `sunak uninstall` (macOS/Linux), Windows: Ordner `%LOCALAPPDATA%\sunak` löschen |

## Konfiguration

Alles lässt sich in der Oberfläche einstellen. Optional per Umgebungsvariable:

| Variable | Standard | Zweck |
|---|---|---|
| `SUNAK_PORT` | `7000` | Port (ist er belegt, wird der nächste freie genommen) |
| `SUNAK_HOST` | `127.0.0.1` | `0.0.0.0` für Zugriff aus dem Netzwerk |
| `SUNAK_DATA` | `~/.sunak` | Ordner für die Datenbank |
| `SUNAK_PASSWORD` | – | Passwort beim Start setzen |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama-Adresse beim ersten Start |
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
| `sunak/server.py` | HTTP-Server, alle API-Endpunkte, Einstellungen, Login |
| `sunak/providers.py` | Anbindung von Ollama und OpenAI-kompatiblen APIs (Streaming) |
| `sunak/research.py` | Websuche und Seitenauswertung für Research |
| `sunak/db.py` | SQLite-Speicher |
| `sunak/static/` | Oberfläche (HTML, CSS, ein JavaScript-File) |

Aufbau, Datenfluss, alle API-Endpunkte, Backends und Erweiterungspunkte beschreibt [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Lizenz

MIT
