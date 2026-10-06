<p align="center">
  <img src="sunak/static/icon.svg" width="72" alt="">
</p>
<h1 align="center">Sunak</h1>
<p align="center">
  Dein privater KI-Arbeitsplatz: Chat, Modellvergleich, Web-Recherche, Dokumente und Gedächtnis.<br>
  Läuft komplett auf deinem Rechner, in Pink und mit Fokus auf einfache Installation.
</p>

> [!WARNING]
> **Komplett vibe coded.** Sunak wurde vollständig von einer KI (Claude) geschrieben, inklusive Installer, Tests und dieser Anleitung. Kein Mensch hat den Code Zeile für Zeile geprüft. Die automatischen Tests laufen zwar auf Linux, macOS und Windows, trotzdem können Fehler und Sicherheitslücken drin sein. Nutzung auf eigene Gefahr. Mach Sunak nicht ungeschützt im Internet erreichbar und leg keine sensiblen Daten hinein, ohne sie zusätzlich zu sichern.

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
> Der Installer merkt sich den Klon, `sunak update` holt Neuerungen dann per `git pull` mit deinen Git-Zugangsdaten. Sunak prüft beim Start und danach höchstens alle 6 Stunden per `git fetch`, ob es Neuerungen gibt, und zeigt dann oben links „✨ Update available“. Installiert wird nur, wenn du auf **Update** klickst.

### Deinstallieren

```bash
sunak uninstall
```

Das entfernt den Befehl `sunak`, den App-Ordner, Desktop- und Menü-Icons, den Autostart und den PATH-Eintrag. Läuft Sunak noch, wird es vorher beendet. Alles Weitere fragt Sunak einzeln, die Vorgabe (Enter) ist immer „behalten“:

1. Sunaks Docker-Container, falls vorhanden,
2. **deine Daten** (Chats, Einstellungen, API-Keys, Mail-Konten in `~/.sunak`),
3. **Ollama selbst** (nativ installiert oder als Docker-Container). Andere Programme können es nutzen. Bei Ja entfernt Sunak es passend zum System: Windows über den Ollama-Deinstaller bzw. winget, macOS über Homebrew oder die App, Linux Dienst, Programm und Benutzer der offiziellen Installation (fragt nach dem `sudo`-Passwort), Snap per `snap remove`. Bei einem Paket der Distribution sagt Sunak, dass der Paketmanager das übernimmt,
4. die **heruntergeladenen Modelle**. Sie belegen viel Platz, wären nach einer Neuinstallation von Ollama aber sofort wieder nutzbar.

Ohne Terminal wird nichts davon gelöscht. Zweimal ausführen schadet nicht.

- Ohne Fragen: `sunak uninstall --yes` (Programm weg, Daten, Ollama und Modelle bleiben). Dazu einzeln: `--purge` (Daten löschen), `--with-ollama` (Ollama deinstallieren), `--with-models` (Modelle löschen).
- Als Einzeiler, auch wenn der Befehl `sunak` fehlt: `curl -fsSL https://raw.githubusercontent.com/M4XM77R/sunak/main/uninstall.sh | bash` (Optionen: `| bash -s -- --yes`), unter Windows `irm https://raw.githubusercontent.com/M4XM77R/sunak/main/uninstall.ps1 | iex` (Optionen vorher als `$env:SUNAK_YES = "1"`, `SUNAK_PURGE`, `SUNAK_WITH_OLLAMA`, `SUNAK_WITH_MODELS`). Im Klon: `./uninstall.sh` bzw. `.\uninstall.ps1`.
- Wer Sunak vor diesem Stand installiert hat, macht erst `sunak update` oder nimmt das Skript; der alte Befehl `sunak uninstall` löschte nach einer Frage auch die Daten.

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
docker compose up -d                                                   # nur CPU, http://localhost:7000
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d   # mit NVIDIA-GPU
docker compose -f docker-compose.yml -f docker-compose.amd.yml up -d   # mit AMD-GPU (Linux)
```

Für NVIDIA braucht der Rechner den NVIDIA-Treiber und das [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), für AMD den `amdgpu`-Treiber (Linux, ROCm-Image `ollama/ollama:rocm`). Auf dem Mac kann Docker die GPU nicht nutzen; dort ist die normale Installation mit der Ollama-App schneller.

### GPU

Sunak rechnet nicht selbst, die Modelle laufen in Ollama. Ollama nutzt eine passende GPU automatisch: NVIDIA über CUDA, AMD über ROCm, Apple Silicon über Metal. Der Ollama-Installer richtet dafür alles ein, die NVIDIA-Karte braucht nur den normalen Treiber. Ohne passende GPU laufen die Modelle auf dem Prozessor, dann sind kleine Modelle die bessere Wahl.

- `sunak gpu` zeigt, welche GPU Sunak gefunden hat; die Installer melden das ebenfalls.
- Die Seite **Models** zeigt GPU und Grafikspeicher, markiert Modelle, die komplett hineinpassen, mit ⚡ und zeigt pro geladenem Modell, ob es auf der GPU oder dem Prozessor läuft. Läuft Ollama trotz GPU auf dem Prozessor, erscheint eine Warnung mit Lösungshinweis.
- Das empfohlene Startmodell richtet sich nach Arbeitsspeicher und Grafikspeicher.
- AMD-Karten, die ROCm nicht offiziell unterstützt, laufen oft mit `HSA_OVERRIDE_GFX_VERSION` (zum Beispiel `10.3.0` für RX 6000, `11.0.0` für RX 7000), gesetzt für den Ollama-Dienst bzw. im `ollama`-Container. Details: [docs.ollama.com/gpu](https://docs.ollama.com/gpu).

## Funktionen

| | |
|---|---|
| 💬 **Chat** | Streaming-Antworten, Volltextsuche über alle Chats, Export als Markdown, JSON oder PDF, Bearbeiten und Neu generieren, Markdown, Tabellen, Code mit Kopier-Knopf, Denkprozess von Reasoning-Modellen ein- und ausklappbar, Dateien anhängen (auch PDF, Word, PowerPoint) per 📎 oder Drag & Drop |
| 🤖 **Claude** | Claude als eigener Anbieter: API-Key eintragen, die verfügbaren Claude-Modelle erscheinen automatisch in der Auswahl. Antworten werden gestreamt, der Denkprozess ist zusammengefasst sichtbar. Funktioniert in Chat, Compare, Research und Documents |
| 📚 **Knowledge** | Eigene Wissensbasis: PDFs, Word (.docx), OpenDocument (.odt), PowerPoint (.pptx), HTML, Markdown, Text, CSV und Code hochladen, im Chat mit 📚 einschalten und Fragen dazu stellen. Antworten zeigen, aus welchen Dateien sie stammen. Volltextsuche über alle Dateien. Alles bleibt lokal, ohne Zusatzsoftware |
| ✉️ **Mail** | Beliebig viele E-Mail-Konten verknüpfen (Gmail, Outlook, iCloud, Yahoo, GMX, WEB.DE, Telekom oder eigener Server über IMAP/SMTP). Posteingang je Konto, Ordner, Suche, Mails lesen ohne sie als gelesen zu markieren, Anhänge herunterladen, Antworten, Weiterleiten, Entwürfe. Die KI fasst Mails zusammen, entwirft Antworten, sortiert den Posteingang („Overview“) oder nimmt eine Mail mit in den Chat. Gesendet wird nur nach Klick auf **Send** |
| 🛠 **Agent** | Agentisches Coding: Das Modell arbeitet in einem Projektordner, den du auswählst. Es liest, sucht und listet Dateien selbst, legt Dateien an, bearbeitet sie (als Diff sichtbar) und führt Befehle aus, etwa die Tests. Jeder Schritt erscheint live im Chat, Schreiben und Befehle nur nach deinem Klick („Apply“, „Allow … in this chat“ oder „Deny“), Stop jederzeit. Kein Zugriff außerhalb des Ordners. Funktioniert mit Claude, Ollama-Modellen mit Tool-Support (z. B. Qwen 3, Llama 3.1+) und OpenAI-kompatiblen APIs; Modelle ohne Tool-Support nutzen ein einfaches Textprotokoll. Standardmäßig aus |
| 🎭 **Personas** | Eigene Systemprompts als Personas, oben im Chat umschaltbar. Mitgeliefert: Assistant, Coder, Writer, Translator, Teacher; alle änderbar, eigene hinzufügbar (Settings → Personas) |
| ⚖️ **Compare** | Ein Prompt an 2 bis 4 Modelle gleichzeitig, Antworten und Geschwindigkeit nebeneinander |
| 🔎 **Research** | Sucht im Web, liest die besten Seiten und schreibt einen Bericht mit Quellenangaben; als Dokument speicherbar |
| 📝 **Documents** | Markdown-Editor mit Autosave, Vorschau, Export und KI-Bearbeitung („kürzer“, „Grammatik korrigieren“), auch nur für markierten Text, mit Rückgängig |
| 🧠 **Notes & Memory** | Notizen; als „memory“ markierte Notizen kennt die KI in jedem Chat |
| 🧩 **Modelle** | Eingebaute Ollama-Verwaltung: GPU-Erkennung (NVIDIA, AMD, Apple Silicon) mit Warnung, wenn Ollama sie nicht nutzt, Modellkatalog mit Empfehlungen passend zu RAM und Grafikspeicher, Download per Klick mit Fortschrittsbalken und Abbrechen, jedes Ollama-Modell per Name, installierte Modelle anzeigen und löschen. Ollama lässt sich aus Sunak heraus starten und unter Windows (winget) und macOS (Homebrew) auch installieren. Zusätzlich jede OpenAI-kompatible API: OpenAI, OpenRouter, Groq, LM Studio, llama.cpp, vLLM |
| 🎨 **Themes** | Acht Themes: Sunak Dark und Sunak Light (Pink), Retro (grünes Terminal mit Monospace-Schrift), Cyberpunk (Neon), Ocean, Forest, Sunset (hell und warm) und 80s Corporate (beige Bürotechnik, marineblaue Titelleiste, Bordeaux, kantige Knöpfe mit 3D-Rand). Umschalten mit 🎨 oben rechts oder mit Vorschau in Settings → Look, dazu eigene Akzentfarben. Alle Themes sind auf gute Lesbarkeit geprüft. Als App installierbar (PWA), handytauglich |
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
| E-Mail-Konto verknüpfen | Settings → Mail accounts → ＋ Add mail account → Adresse und App-Passwort eintragen (die Server werden für bekannte Anbieter automatisch ausgefüllt) → Test connection → Save account. Weitere Konten genauso |
| Mails mit KI bearbeiten | ✉️ Mail → Mail öffnen → ✨ Summarize, ↩ Reply und dann ✨ Draft reply (optional mit Hinweis wie „zusagen, aber erst nächste Woche“), oder 💬 Ask in chat |
| Claude nutzen | Settings → Providers → Preset „Claude (Anthropic)“ → API-Key von [console.anthropic.com](https://console.anthropic.com) einfügen → Save settings. Alternativ beim ersten Start „Use Claude with an API key“ klicken |
| Agent-Modus (agentisches Coding) | Settings → Agent → „Enable agent mode“ → Save settings. Dann im Chat 🛠 neben dem Eingabefeld einschalten, den Projektordner eintragen (voller Pfad) und sagen, was zu tun ist. Änderungen und Befehle erscheinen zur Freigabe; „Ask again“ nimmt eine Freigabe „für diesen Chat“ zurück |
| Anderes Cloud-Modell nutzen | Settings → Providers → Preset wählen → API-Key eintragen → Save settings |
| Vom Handy nutzen | `sunak --host 0.0.0.0`, in Settings ein Passwort setzen, dann `http://<PC-IP>:7000` öffnen |
| Sunak beenden | Settings → ⏻ Stop Sunak, oder `sunak stop` |
| Theme wechseln | 🎨 oben rechts, oder Settings → Look (mit Vorschau) |
| Läuft Sunak? | `sunak status` |
| Welche GPU wird genutzt? | `sunak gpu`, oder die Seite Models |
| Automatisch beim Anmelden starten | `sunak autostart on` (aus: `sunak autostart off`) |
| Desktop-Icon neu anlegen | `sunak shortcut` |
| Aktualisieren | Bei „✨ Update available“ oben links auf **Update** klicken: Sunak installiert die neue Version und startet neu. Oder im Terminal `sunak update` (holt die neueste Version und beendet ein laufendes Sunak, damit der nächste Start sie nutzt) |
| Update-Hinweis abschalten | Settings → Updates → Haken bei „Check for updates“ entfernen → Save settings |
| Version anzeigen | `sunak version` |
| Deinstallieren | `sunak uninstall`: entfernt das Programm und fragt einzeln nach Daten, Ollama und Modellen (Standard: behalten). Details unter [Deinstallieren](#deinstallieren) |

## E-Mail

Sunak spricht IMAP (lesen) und SMTP (senden) direkt mit der Python-Standardbibliothek, ohne Zusatzpakete und ohne Umweg über fremde Server.

- **App-Passwort:** Gmail, iCloud und Yahoo verlangen ein App-Passwort statt des normalen Passworts (bei Gmail erst nach Einschalten der Bestätigung in zwei Schritten). Bei GMX und WEB.DE muss IMAP vorher in den Einstellungen des Postfachs freigeschaltet werden, bei der Telekom gilt das eigene E-Mail-Passwort. Sunak zeigt beim Einrichten den passenden Hinweis.
- **Sicherheit:** Passwörter liegen wie API-Keys nur in der lokalen Datenbank, werden nie protokolliert und nie an den Browser zurückgegeben; das Backup enthält sie nicht. Verbindungen laufen über SSL/TLS oder STARTTLS mit Zertifikatsprüfung. Unverschlüsselt (und mit selbst signiertem Zertifikat) verbindet Sunak sich nur mit `localhost`, etwa mit der Proton Mail Bridge.
- **Nichts passiert von selbst:** Ordner werden nur lesend geöffnet, Mails bleiben ungelesen. Gesendet wird nur nach Klick auf **Send** und einer Rückfrage, Entwürfe landen nur mit **Save draft** im Entwürfe-Ordner. KI-Antworten erscheinen als Entwurf im Formular.
- **Mail-Inhalt ist kein Befehl:** Die KI bekommt Mails ausdrücklich als Daten von Dritten; Anweisungen darin soll sie ignorieren. Sie hat ohnehin keine Werkzeuge und kann selbst nichts senden.

**Grenzen (ehrlich):**

- **Kein OAuth.** Anmeldung geht nur per Passwort bzw. App-Passwort. OAuth bräuchte eine bei Google bzw. Microsoft registrierte App mit Client-ID; das lässt sich ohne fremden Dienst nicht sauber mitliefern. Microsoft (Outlook, Hotmail, Microsoft 365) erlaubt für fremde Programme oft nur noch OAuth. Lehnt der Server die Anmeldung ab, funktioniert das Konto in Sunak nicht.
- HTML-Mails werden als Text angezeigt (keine Bilder, keine Formatierung, dafür auch kein Tracking).
- Eigene Anhänge beim Schreiben und Weiterleiten von Anhängen gehen noch nicht; empfangene Anhänge lassen sich herunterladen.
- Keine Benachrichtigung bei neuen Mails, kein Verschieben oder Löschen. Jede Aktion baut eine neue Verbindung auf, das dauert je nach Anbieter ein bis zwei Sekunden.
- Getestet ist alles gegen simulierte IMAP- und SMTP-Server, nicht gegen echte Anbieter.

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
