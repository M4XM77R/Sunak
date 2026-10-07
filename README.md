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
- Die Seite **Models** zeigt GPU und Grafikspeicher, markiert Modelle, die komplett hineinpassen, mit „fits GPU“ und zeigt pro geladenem Modell, ob es auf der GPU oder dem Prozessor läuft. Läuft Ollama trotz GPU auf dem Prozessor, erscheint eine Warnung mit Lösungshinweis.
- Das empfohlene Startmodell richtet sich nach Arbeitsspeicher und Grafikspeicher.
- AMD-Karten, die ROCm nicht offiziell unterstützt, laufen oft mit `HSA_OVERRIDE_GFX_VERSION` (zum Beispiel `10.3.0` für RX 6000, `11.0.0` für RX 7000), gesetzt für den Ollama-Dienst bzw. im `ollama`-Container. Details: [docs.ollama.com/gpu](https://docs.ollama.com/gpu).

## Funktionen

| | |
|---|---|
| 💬 **Chat** | Streaming-Antworten, Volltextsuche über alle Chats, Export als Markdown, JSON oder PDF, Bearbeiten und Neu generieren, Markdown, Tabellen, Code mit Kopier-Knopf, Denkprozess von Reasoning-Modellen ein- und ausklappbar, Dateien anhängen (auch PDF, Word, PowerPoint) per Büroklammer oder Drag & Drop, **Bilder verstehen**: Fotos und Screenshots anhängen oder einfügen (`Strg+V`), Vision-Modelle wie qwen2.5vl, gemma3, llama3.2-vision oder Claude beschreiben sie und beantworten Fragen dazu |
| 🤖 **Claude** | Claude als eigener Anbieter: API-Key eintragen, die verfügbaren Claude-Modelle erscheinen automatisch in der Auswahl. Antworten werden gestreamt, der Denkprozess ist zusammengefasst sichtbar. Funktioniert in Chat, Compare, Research und Documents |
| 📚 **Knowledge** | Eigene Wissensbasis: PDFs, Word (.docx), OpenDocument (.odt), PowerPoint (.pptx), HTML, Markdown, Text, CSV und Code hochladen, im Chat mit dem Buch-Knopf einschalten und Fragen dazu stellen. Antworten zeigen, aus welchen Dateien sie stammen. Volltextsuche über alle Dateien. Alles bleibt lokal, ohne Zusatzsoftware |
| ✉️ **Mail** | Beliebig viele E-Mail-Konten verknüpfen (Gmail, Outlook, iCloud, Yahoo, GMX, WEB.DE, Telekom oder eigener Server über IMAP/SMTP). Posteingang je Konto, Ordner, Suche, Mails lesen ohne sie als gelesen zu markieren, Anhänge herunterladen, Antworten, Weiterleiten (mit den Anhängen), eigene Anhänge, Entwürfe, Verschieben, Löschen über den Papierkorb, Hinweis bei neuer Mail. Die KI fasst Mails zusammen, entwirft Antworten, sortiert den Posteingang („Overview“) oder nimmt eine Mail mit in den Chat. Gesendet wird nur nach Klick auf **Send** |
| 📅 **Kalender** | Monatsansicht mit allen Kalendern: Sunaks eigener Kalender, CalDAV-Konten (iCloud, GMX, WEB.DE, Yahoo, mailbox.org, Posteo, Fastmail, Nextcloud; oft mit der Anmeldung eines verknüpften Mail-Kontos) und abonnierte Kalenderadressen (ICS, z. B. Google oder Outlook, nur lesen). Termine anlegen, ändern und löschen, auch ganztägig und wiederkehrend; Wiederholungen, Zeitzonen und Sommerzeit werden richtig gerechnet. „Hinzufügen“ macht aus einem Satz wie „Zahnarzt nächsten Dienstag 10 Uhr“ einen Termin, „In den Kalender“ liest ihn aus einer E-Mail; gespeichert wird erst nach deinem Klick |
| 🛠 **Agent** | Agentisches Coding: Das Modell arbeitet in einem Projektordner, den du auswählst. Es liest, sucht und listet Dateien selbst, legt Dateien an, bearbeitet sie (als Diff sichtbar) und führt Befehle aus, etwa die Tests. Jeder Schritt erscheint live im Chat, Schreiben und Befehle nur nach deinem Klick („Apply“, „Allow … in this chat“ oder „Deny“), Stop jederzeit. Kein Zugriff außerhalb des Ordners. Funktioniert mit Claude, Ollama-Modellen mit Tool-Support (z. B. Qwen 3, Llama 3.1+) und OpenAI-kompatiblen APIs; Modelle ohne Tool-Support nutzen ein einfaches Textprotokoll. Standardmäßig aus |
| 🔌 **Werkzeuge (MCP)** | MCP-Server (Model Context Protocol) geben dem Modell Werkzeuge: Dateien, Webseiten lesen, Uhrzeit, Gedächtnis oder jeden anderen MCP-Server, als Programm auf dem Computer (stdio) oder über eine Adresse (Streamable HTTP). Im Chat mit dem Stecker-Knopf einschalten, auch zusammen mit dem Agent-Modus. Vor jedem Werkzeugaufruf fragt Sunak („Allow“, „Allow … in this chat“, „Deny“) und zeigt die Eingabe. Umgebungswerte und Tokens bleiben auf dem Computer |
| 🎨 **Bilder erzeugen** | Der Bild-Knopf neben dem Eingabefeld macht aus einer Beschreibung ein Bild. Am einfachsten mit Sunaks eigenem Bildprogramm (stable-diffusion.cpp): auf der Modelle-Seite mit einem Klick einrichten und Bildmodelle (SD-Turbo, SD 1.5, SDXL-Turbo, SDXL oder per Suche von Hugging Face) mit Lizenzhinweis, Fortschritt, Pause/Fortsetzen und Löschen laden, ohne Python-Pakete. Alternativ ein vorhandenes Automatic1111 (auch Forge, SD.Next) oder ComfyUI. Format wählbar (quadratisch, hoch, quer), optional was nicht im Bild sein soll; Fortschrittsbalken, Stop, „Noch einmal“ für eine neue Variante, Download. Die Bilder bleiben im Chat. Optional, standardmäßig aus |
| 🎭 **Personas** | Eigene Systemprompts als Personas, oben im Chat umschaltbar. Mitgeliefert: Assistant, Coder, Writer, Translator, Teacher; alle änderbar, eigene hinzufügbar (Settings → Personas) |
| ⚖️ **Compare** | Ein Prompt an 2 bis 4 Modelle gleichzeitig, Antworten und Geschwindigkeit nebeneinander |
| 🌐 **Web-Suche im Chat** | Der Globus-Knopf neben dem Eingabefeld: Sunak sucht zur Frage im Web (DuckDuckGo ohne Konto oder eigenes SearXNG), liest die besten Seiten und das Modell antwortet mit Quellenangaben [1], [2]. Bei Folgefragen formuliert das Modell die Suchanfrage selbst. Gilt pro Chat, standardmäßig aus |
| 🔎 **Research** | Sucht im Web, liest die besten Seiten und schreibt einen Bericht mit Quellenangaben; als Dokument speicherbar |
| 📝 **Documents** | Markdown-Editor mit Autosave, Vorschau, Export und KI-Bearbeitung („kürzer“, „Grammatik korrigieren“), auch nur für markierten Text, mit Rückgängig |
| 🧠 **Notes & Memory** | Notizen; als „memory“ markierte Notizen kennt die KI in jedem Chat |
| 🧩 **Modelle** | Modellsuche mit Filtern (Chat, Bilder verstehen, Programmieren, Logik, Bild; Größe; passt zu meinem Computer) über Sunaks Katalog, auf Knopfdruck auch in der Ollama-Bibliothek und auf Hugging Face (GGUF-Modelle lädt Ollama direkt); ist das Netz weg, bleibt es still beim eigenen Katalog. Eingebaute Ollama-Verwaltung: GPU-Erkennung (NVIDIA, AMD, Apple Silicon) mit Warnung, wenn Ollama sie nicht nutzt, Modellkatalog mit Empfehlungen passend zu RAM und Grafikspeicher, Download per Klick mit Fortschrittsbalken und Abbrechen, jedes Ollama-Modell per Name, installierte Modelle anzeigen und löschen. Ollama lässt sich aus Sunak heraus starten und unter Windows (winget) und macOS (Homebrew) auch installieren. Zusätzlich jede OpenAI-kompatible API: OpenAI, OpenRouter, Groq, LM Studio, llama.cpp, vLLM |
| 🎨 **Themes** | Acht Themes: Sunak Dark und Sunak Light (Pink), Retro (grünes Terminal mit Monospace-Schrift), Cyberpunk (Neon), Ocean, Forest, Sunset (hell und warm) und 80s Corporate (beige Bürotechnik, marineblaue Titelleiste, Bordeaux, kantige Knöpfe mit 3D-Rand). Umschalten mit dem Paletten-Knopf oben rechts oder mit Vorschau in Settings → Look, dazu eigene Akzentfarben. Alle Themes sind auf gute Lesbarkeit geprüft. Als App installierbar (PWA), handytauglich, Handy-Zugriff im WLAN per QR-Code |
| 🎤 **Sprechen und Vorlesen** | Das Mikrofon neben dem Eingabefeld diktiert statt zu tippen, der Lautsprecher unter einer Antwort liest sie vor. Ganz lokal mit einem eigenen Whisper-Server (whisper.cpp, Speaches/faster-whisper-server, LocalAI) oder der Offline-Erkennung von Chrome; die Online-Erkennung des Browsers nur, wenn du sie erlaubst. Vorlesen mit den Stimmen des Geräts |
| 🌍 **Sprachen** | Oberfläche auf Deutsch oder Englisch, standardmäßig in der Sprache des Browsers, umschaltbar unter Settings → Look → Language (Einstellungen → Aussehen → Sprache). Weitere Sprachen lassen sich als eine Datei ergänzen |
| 👥 **Profile** | Mehrere Personen an einem Sunak: Jedes Profil hat eigene Chats, Dokumente, Notizen, Wissensbasis, Mail-Konten, Kalender, Personas, Theme und Sprache, auf Wunsch mit PIN. Anbieter, Modelle und MCP-Server sind gemeinsam. Nur Admin-Profile ändern Anbieter, Agent, Werkzeuge, Passwort und Profile; Agent-Modus und MCP-Werkzeuge stehen nur Admins zur Verfügung |
| 🔒 **Sicherheit** | Läuft standardmäßig nur auf `localhost`; optionales Passwort; Daten in einer SQLite-Datei unter `~/.sunak` |

<p align="center"><img src="docs/models.png" alt="Modelle" width="820"></p>
<p align="center"><img src="docs/onboarding.png" alt="Erster Start" width="410"> <img src="docs/compare.png" alt="Compare" width="410"></p>

## Bedienung

| Aktion | So geht's |
|---|---|
| Senden / neue Zeile | `Enter` / `Shift+Enter` |
| Neuer Chat | `Strg+K` (Mac: `⌘K`) |
| Modell herunterladen | Models → Modell aussuchen → Download (Abbrechen jederzeit möglich, der Download läuft beim nächsten Mal weiter) |
| Modell wechseln | Auswahl oben rechts |
| Persona wechseln | Auswahl oben neben dem Modell, gilt für den aktuellen Chat. Eigene Personas: Settings → Personas |
| Alte Chats finden | Suchfeld über der Chatliste: durchsucht Titel und alle Nachrichten, ein Klick springt zur Stelle |
| Chat exportieren | Download-Knopf oben rechts → Markdown, JSON oder Drucken/PDF |
| Alles sichern | Settings → Data → Download backup (ohne API-Keys und Passwort) |
| Aktuelles fragen (Web-Suche) | den Globus-Knopf neben dem Eingabefeld einschalten, dann normal fragen. Die Quellen erscheinen über der Antwort und lassen sich anklicken. Dabei geht die Suchanfrage an DuckDuckGo (bzw. an `SEARXNG_URL`); für einen gründlichen Bericht gibt es Research |
| Fragen zu einem Bild | Bild per Büroklammer anhängen, ins Chatfenster ziehen oder einen Screenshot mit `Strg+V` einfügen, Frage dazuschreiben, senden. Nötig ist ein Modell mit Bildverständnis (z. B. `qwen2.5vl:7b` oder `gemma3:4b` unter Models, oder Claude); andere Modelle melden das sofort, die Nachricht bleibt dann im Eingabefeld |
| Fragen zu eigenen Dateien | Knowledge → Dateien hineinziehen → im Chat den Buch-Knopf neben dem Eingabefeld einschalten. Für eine einzelne Datei reicht auch die Büroklammer |
| E-Mail-Konto verknüpfen | Settings → Mail accounts → Add mail account → Adresse und App-Passwort eintragen (die Server werden für bekannte Anbieter automatisch ausgefüllt) → Test connection → Save account. Weitere Konten genauso |
| Echtes Mail-Konto prüfen | `sunak mail-selftest` (mit `--account adresse` bei mehreren Konten): meldet sich an, liest, sendet sich selbst eine Mail mit Anhang, leitet ihn als Entwurf weiter, verschiebt und löscht, und räumt seine Testmails am Ende weg. Siehe [E-Mail](#e-mail) |
| Mails mit KI bearbeiten | Mail → Mail öffnen → Summarize, Reply und dann Draft reply (optional mit Hinweis wie „zusagen, aber erst nächste Woche“), oder Ask in chat |
| Claude nutzen | Settings → Providers → Preset „Claude (Anthropic)“ → API-Key von [console.anthropic.com](https://console.anthropic.com) einfügen → Save settings. Alternativ beim ersten Start „Use Claude with an API key“ klicken |
| Agent-Modus (agentisches Coding) | Settings → Agent → „Enable agent mode“ → Save settings. Dann im Chat den Terminal-Knopf neben dem Eingabefeld einschalten, den Projektordner eintragen (voller Pfad) und sagen, was zu tun ist. Änderungen und Befehle erscheinen zur Freigabe; „Ask again“ nimmt eine Freigabe „für diesen Chat“ zurück |
| MCP-Server nutzen | Settings → Tools (MCP) → „Preset…“ wählen oder „Add server“: Name, Typ „Program“ mit dem Startbefehl (z. B. `npx -y @modelcontextprotocol/server-memory`, braucht Node.js; `uvx mcp-server-fetch` braucht uv) oder „Address (HTTP)“ mit der URL und optional einem Token. „Test“ startet den Server einmal und zeigt seine Werkzeuge, dann Save settings. Im Chat den Stecker-Knopf einschalten. Geheimnisse wie API-Keys des Servers als `NAME=Wert` unter den Umgebungsvariablen eintragen |
| Kalender verbinden | Settings → Calendars → „Add calendar“. Für CalDAV unter „Own login“ ein verknüpftes Mail-Konto wählen (Adresse und Benutzername werden ausgefüllt, das Passwort des Mail-Kontos wird verwendet) oder Anbieter, Benutzername und (App-)Passwort eintragen. Google und Outlook.com bieten kein CalDAV mit Passwort: dort die geheime iCal-Adresse als „ICS address“ abonnieren. Welche Kalender angezeigt werden, wählst du in der Liste rechts im Kalender |
| Anderes Cloud-Modell nutzen | Settings → Providers → Preset wählen → API-Key eintragen → Save settings |
| Vom Handy oder Tablet nutzen | Settings → Security: Passwort setzen. Dann Settings → Phone & tablet → „Allow phones and tablets in my network“ einschalten und den QR-Code mit der Handykamera scannen (oder die angezeigte Adresse eintippen). Handy und Computer müssen im selben WLAN sein; fragt die Firewall des Computers, Python erlauben. Für ein App-Icon im Browsermenü „Zum Startbildschirm hinzufügen“ wählen. Die Einstellung bleibt nach einem Neustart erhalten, ohne Passwort geht sie nicht |
| Bilder erzeugen (eigenes Programm) | Models → Filter „Image“ → „Set up the image program“: Sunak schlägt die passende Version vor (NVIDIA: CUDA, andere Grafikkarten: Vulkan, Mac: Metal, sonst nur Prozessor), Install. Dann ein Bildmodell herunterladen (für den Anfang SD-Turbo, 5 GB) und im Chat den Bild-Knopf einschalten. Sunak führt durch die Schritte: Ist das Programm da, aber noch kein Modell geladen, steht auf der Models-Seite „Next step“ und der (blasse) Bild-Knopf im Chat sagt per Klick, was fehlt. Sobald Programm und Modell da sind, wählt Sunak das Modell selbst und schaltet den Bildmodus ein. Fehlermeldungen des Programms erscheinen im Chat. Auch im normalen Chat: schreibst du „generiere ein Bild von …“ (ein Chatmodell kann nicht malen), fragt Sunak, ob es das Bild mit dem Bildgenerator machen soll (OK) oder die Nachricht normal senden (Abbrechen); ist noch nichts eingerichtet, zeigt es, was fehlt. Das Programm ist je nach Version etwa 20 bis 500 MB groß (CUDA am größten), Modelle 4 bis 8 GB. Mit Grafikkarte dauert ein Bild Sekunden, nur mit dem Prozessor eine bis mehrere Minuten. Abgebrochene Downloads laufen beim nächsten Klick weiter |
| Modelle suchen | Models → Suchfeld: filtert sofort Sunaks Katalog; „Search online“ fragt zusätzlich ollama.com und Hugging Face. Bei Hugging-Face-Treffern zeigt „Show files“ Größe, Quantisierung und Lizenz, Download lädt das GGUF-Modell über Ollama (`hf.co/…`) bzw. ein Bildmodell in Sunaks Bildprogramm. Modelle, die eine Anmeldung bei Hugging Face verlangen, kann Sunak nicht laden |
| Bilder erzeugen (Automatic1111/ComfyUI) | Ein Stable-Diffusion-Programm installieren, z. B. [Automatic1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui) bzw. Forge (mit der Option `--api` starten) oder [ComfyUI](https://github.com/comfyanonymous/ComfyUI), und ein Modell hineinlegen. Dann Settings → Image generation → Programm wählen, Adresse leer lassen für die übliche lokale (`http://127.0.0.1:7860` bzw. `:8188`), „Test“ zeigt die Modelle → Save settings. Im Chat den Bild-Knopf einschalten, das Bild beschreiben und senden. Für SDXL- und Flux-Modelle die Bildgröße 1024 px wählen |
| Profile anlegen | Settings → Profile → „Add profile“: Name, optional ein eigenes Emoji (sonst ein Personen-Icon), optional PIN (mindestens 4 Zeichen) und ob das Profil Admin sein soll. Beim nächsten Öffnen fragt Sunak „Who is using Sunak?“; gewechselt wird über den Namen oben links. Das erste Profil ist das Hauptprofil mit allen bisherigen Daten, es bleibt immer Admin und lässt sich nicht löschen. Eine PIN trennt die Profile in der App, schützt aber nicht vor jemandem, der am Computer die Dateien unter `~/.sunak` öffnen kann |
| Sunak beenden | Settings → ⏻ Stop Sunak, oder `sunak stop` |
| Theme wechseln | Paletten-Knopf oben rechts, oder Settings → Look (mit Vorschau) |
| Diktieren | Mikrofon neben dem Eingabefeld klicken, sprechen, noch einmal klicken. Der Text landet im Eingabefeld. Ganz lokal mit Whisper: z. B. whisper.cpp mit `whisper-server -m ggml-base.bin` starten und unter Settings → Voice `http://localhost:8080/inference` eintragen (Speaches/faster-whisper-server: `http://localhost:8000/v1` und den Modellnamen). Ohne Whisper nutzt Sunak die Offline-Erkennung von Google Chrome; die Online-Erkennung (Chrome schickt den Ton an Google) nur, wenn sie unter Settings → Voice erlaubt ist. Das Mikrofon geht nur am Computer selbst, nicht über den Handy-Zugriff |
| Vorlesen lassen | Lautsprecher unter einer Antwort, noch einmal klicken stoppt. Stimme: Settings → Voice (pro Gerät, mit ▶ Test) |
| Sprache wechseln | Settings → Look → Language (auf Deutsch: Einstellungen → Aussehen → Sprache). „Automatisch“ folgt der Sprache des Browsers; die Seite lädt danach neu. Die Wahl gilt für alle Geräte |
| Alle Befehle und Optionen | `sunak -h` zeigt sie gruppiert mit je einem Beispiel, `sunak <befehl> -h` (oder `sunak help <befehl>`) die Details eines Befehls. Bei Tippfehlern schlägt Sunak den passenden Befehl vor. Farben lassen sich mit `NO_COLOR=1` abschalten |
| Läuft Sunak? | `sunak status` |
| Welche GPU wird genutzt? | `sunak gpu`, oder die Seite Models |
| Automatisch beim Anmelden starten | `sunak autostart on` (aus: `sunak autostart off`) |
| Desktop-Icon neu anlegen | `sunak shortcut` |
| Aktualisieren | Bei „Update available“ oben links auf **Update** klicken: Sunak installiert die neue Version und startet neu. Oder im Terminal `sunak update` (holt die neueste Version und beendet ein laufendes Sunak, damit der nächste Start sie nutzt) |
| Update-Hinweis abschalten | Settings → Updates → Haken bei „Check for updates“ entfernen → Save settings |
| Version anzeigen | `sunak version` (steht auch unter Settings → About). Jede Änderung erhöht die Version (`sunak/__init__.py`): Patch für Fehlerbehebungen, Minor für neue Funktionen; Sunak bleibt unter 1.0, bis der Maintainer 1.0 freigibt |
| Deinstallieren | `sunak uninstall`: entfernt das Programm und fragt einzeln nach Daten, Ollama und Modellen (Standard: behalten). Details unter [Deinstallieren](#deinstallieren) |

## E-Mail

Sunak spricht IMAP (lesen) und SMTP (senden) direkt mit der Python-Standardbibliothek, ohne Zusatzpakete und ohne Umweg über fremde Server.

- **App-Passwort:** Gmail, iCloud und Yahoo verlangen ein App-Passwort statt des normalen Passworts (bei Gmail erst nach Einschalten der Bestätigung in zwei Schritten). Bei GMX und WEB.DE muss IMAP vorher in den Einstellungen des Postfachs freigeschaltet werden, bei der Telekom gilt das eigene E-Mail-Passwort. Sunak zeigt beim Einrichten den passenden Hinweis.
- **Sicherheit:** Passwörter liegen wie API-Keys nur in der lokalen Datenbank, werden nie protokolliert und nie an den Browser zurückgegeben; das Backup enthält sie nicht. Verbindungen laufen über SSL/TLS oder STARTTLS mit Zertifikatsprüfung. Unverschlüsselt (und mit selbst signiertem Zertifikat) verbindet Sunak sich nur mit `localhost`, etwa mit der Proton Mail Bridge.
- **Nichts passiert von selbst:** Ordner werden nur lesend geöffnet, Mails bleiben ungelesen. Gesendet wird nur nach Klick auf **Send** und einer Rückfrage, Entwürfe landen nur mit **Save draft** im Entwürfe-Ordner. KI-Antworten erscheinen als Entwurf im Formular.
- **Anhänge:** Die Büroklammer im Formular hängt Dateien an (zusammen höchstens 17 MB, Gmail erlaubt 25 MB samt Kodierung). Beim Weiterleiten gehen die Anhänge der Original-Mail mit; jeder lässt sich vorher mit dem x entfernen. Der Server holt sie selbst aus dem Postfach, der Browser lädt sie nicht erst herunter.
- **Verschieben und Löschen:** In der Leseansicht „Move to…“ und Delete. Löschen verschiebt nach Rückfrage in den Papierkorb; endgültig gelöscht wird nur im Papierkorb (oder bei Konten ohne Papierkorb), mit eigener Rückfrage. Bei Gmail sind Ordner Labels: Verschieben nimmt das alte Label weg und setzt das neue, Löschen legt die Mail in `[Gmail]/Papierkorb`, wo Google sie nach 30 Tagen selbst entfernt.
- **Neue Mails:** Solange Sunak offen ist, schaut es alle 2 Minuten in jeden Posteingang (nur lesend). Neue ungelesene Mails melden sich mit einem Hinweis, am Knopf Mail steht die Zahl der ungelesenen. Mit „Also as desktop notification“ (Settings → Mail accounts) kommt die Meldung auch als Desktop-Benachrichtigung, wenn Sunak im Hintergrund ist; das geht über `localhost` oder https. Abschalten: Haken bei „Tell me about new mail“ entfernen.
- **Echtes Konto testen:** `sunak mail-selftest` prüft ein verknüpftes Konto Schritt für Schritt gegen den echten Anbieter: IMAP-Anmeldung und Ordner, Posteingang lesen, SMTP-Anmeldung, Hinweis auf neue Mail (legt eine ungelesene Testmail in den Posteingang), Löschen in den Papierkorb und zurückverschieben, Senden an sich selbst mit Anhang, Empfang und unveränderter Anhang, Weiterleiten des Anhangs als Entwurf, Aufräumen. Jede Testmail trägt eine Zufallsmarke im Betreff, nur diese Mails werden angefasst und am Ende endgültig gelöscht (`--keep` behält sie). Das Passwort kommt aus Sunaks Einstellungen und wird nie ausgegeben; mit `--new` tippst du Adresse und App-Passwort stattdessen ein (nicht gespeichert). Gmail: Bestätigung in zwei Schritten einschalten, dann unter https://myaccount.google.com/apppasswords ein App-Passwort erzeugen.
- **Mail-Inhalt ist kein Befehl:** Die KI bekommt Mails ausdrücklich als Daten von Dritten; Anweisungen darin soll sie ignorieren. Sie hat ohnehin keine Werkzeuge und kann selbst nichts senden.

**Grenzen (ehrlich):**

- **Kein OAuth.** Anmeldung geht nur per Passwort bzw. App-Passwort. OAuth bräuchte eine bei Google bzw. Microsoft registrierte App mit Client-ID; das lässt sich ohne fremden Dienst nicht sauber mitliefern. Microsoft (Outlook, Hotmail, Microsoft 365) erlaubt für fremde Programme oft nur noch OAuth. Lehnt der Server die Anmeldung ab, funktioniert das Konto in Sunak nicht.
- HTML-Mails werden als Text angezeigt (keine Bilder, keine Formatierung, dafür auch kein Tracking).
- Der Hinweis auf neue Mail kommt nur, solange Sunak im Browser offen ist (kein Hintergrunddienst, kein IMAP IDLE), also mit bis zu 2 Minuten Verzug. Jede Aktion baut eine neue Verbindung auf, das dauert je nach Anbieter ein bis zwei Sekunden.
- Verschieben und Löschen gehen je Mail, nicht für mehrere auf einmal.
- Die automatischen Tests laufen gegen simulierte IMAP- und SMTP-Server (auch ohne `MOVE`/`UIDPLUS`). Gegen einen echten Anbieter prüft `sunak mail-selftest` auf deinem Rechner.

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
