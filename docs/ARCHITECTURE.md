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
| `sunak/__main__.py` | Kommandozeile (`python -m sunak`): öffnet ein bereits laufendes Sunak im Browser, sonst sucht es einen freien Port, startet den Server und öffnet den Browser. Befehle `status`, `stop`, `update`, `version`, `gpu`, `mail-selftest`, `autostart on\|off\|status`, `shortcut`, `uninstall`, `help`; Startoptionen `--port`, `--host`, `--data-dir`, `--no-browser`, `--version`. Alle stehen mit Gruppe, Kurztext und Beispiel in `COMMANDS`; daraus entstehen `sunak -h`, `sunak <befehl> -h` und der Hinweis „Did you mean …?“ bei Tippfehlern. Farben nur im Terminal und ohne `NO_COLOR` |
| `sunak/gpu.py` | GPU-Erkennung ohne Zusatzpakete: `nvidia-smi`, `/sys/class/drm` (Linux), Registry (Windows), Apple Silicon; Auswertung von Ollamas `/api/ps` und Warnung bei CPU-Betrieb |
| `sunak/updates.py` | Update-Prüfung per git (neue Commits im Klon, aus dem installiert wurde) und Hilfsprozess für den Update-Knopf: wartet auf das Ende des Servers, installiert das Update, startet Sunak neu |
| `sunak/desktop.py` | Desktop-Integration: laufendes Sunak erkennen (`/api/status` mit `Server: Sunak/…`) und beenden, Autostart-Datei und Desktop-Icon je Betriebssystem |
| `start.py` | Start direkt aus dem Repository-Ordner ohne Installation (Windows: Doppelklick) |
| `sunak/server.py` | `App` (Zustand, Einstellungen, Modellauswahl, Login, Prompt-Aufbau) und `Handler` (HTTP-Routing, alle API-Endpunkte) |
| `sunak/db.py` | SQLite-Speicher: Chats, Nachrichten, Dokumente, Notizen, Einstellungen |
| `sunak/providers.py` | Backends: Ollama, Claude (Anthropic Messages API) und OpenAI-kompatible APIs, Streaming, Modell-Download |
| `sunak/ollama.py` | Native Ollama-Integration: Modellkatalog, Status, lokales Ollama finden, starten und installieren |
| `sunak/research.py` | Websuche, Seiten lesen, Prompt für den Recherchebericht |
| `sunak/agent.py` | Agent-Modus: Werkzeuge im Projektordner (Pfadprüfung), Befehle mit Zeit- und Ausgabelimit, Tool-Calling je Backend, Textprotokoll als Ersatz, Agent-Schleife mit Freigaben |
| `sunak/extract.py` | Text aus hochgeladenen Dateien: PDF (eigener Leser), .docx, .odt, .pptx, HTML, Text |
| `sunak/mail.py` | E-Mail: Konten prüfen, IMAP (Ordner, Liste, Suche, Mail als Text, Anhänge, Entwürfe, Verschieben, Löschen, neue Mail) und SMTP (Senden mit Anhängen), Anbieter-Vorlagen, Prompts für die KI |
| `sunak/mailtest.py` | `sunak mail-selftest`: echtes Konto Schritt für Schritt prüfen, nur mit eigenen Testmails |
| `sunak/images.py` | Bilder im Chat: Prüfung (Dateisignatur, Größe, Anzahl), Ablage in `<data>/images`, Anhängen an die Nachrichten für das Modell, Aufräumen |
| `sunak/qr.py` | QR-Code-Erzeuger ohne Abhängigkeiten, für den Handy-Zugriff |
| `sunak/cal.py` | Kalender: iCalendar lesen und schreiben, Wiederholungen (RRULE, EXDATE, verschobene Termine), Zeitzonen, CalDAV-Client (Kalender finden, Termine lesen, anlegen, ändern, löschen), ICS-Abos, Termin aus Text per Modell |
| `sunak/mcp.py` | MCP-Client: Server als Programm (stdio) oder über HTTP (Streamable HTTP) starten, Werkzeuge auflisten und aufrufen, Einstellungen prüfen (Geheimnisse bleiben auf dem Server) |
| `sunak/intent.py` | Erkennt Bildwünsche im Chat: `classify` gibt `yes` (Verb wie generiere/erstell/mach/mal/zeichn/draw/make + Bildwort wie Bild/Foto/Logo/picture/image, oder eine Kurzform ohne Verb wie „a picture of: …“, „Bild von …“, oder ein direkter Zeichenbefehl wie „draw a cat“, „zeichne einen Drachen“; jeweils keine Frage, kein Technik-Wort, nicht „ich mache …“), `maybe` (nur Zeichenverb am Anfang wie „mal mir eine Katze“, Bildwort mit Bitte, Frage- oder Technikform) oder `no`; `maybe` und `no` führen nur über ein JA des Chatmodells zu einem Bild (kann es nicht antworten, sind sie normaler Chat); `messages`/`parse` sind die Ja/Nein-Frage ans Chatmodell, `subject` die Beschreibung ohne die Bitte (Fallback-Prompt) |
| `sunak/imagegen.py` | Bildgenerierung: Automatic1111 (`/sdapi/v1/txt2img`, Fortschritt, Abbruch) und ComfyUI (Standard-Workflow über `/prompt`, `/history`, `/view`), Bildgrößen, Modellliste |
| `sunak/log.py` | Logging: ein Logger `sunak` mit Teilen (`sunak.http`, `sunak.queue`, `sunak.image`, `sunak.app`, `sunak.main`), `setup(data_dir)` hängt zwei Handler an: Terminal (stderr, Farben nur in einem Terminal und ohne `NO_COLOR`) und `<Datenordner>/logs/sunak.log` (`RotatingFileHandler`, 10 MB je Datei, vier Sicherungen, zusammen höchstens 50 MB, Datei nur für den Nutzer lesbar). `redact` maskiert in jeder Zeile Geheimnisse (`add_secret` für die API-Schlüssel der Anbieter, außerdem Muster für `password=…`, Bearer-Tokens, `sk-…`, `?key=…`, lange Hex-Zeichenketten). Ohne `setup` (Tests) bleibt der Logger still |
| `sunak/reports.py` | Fehlerberichte als GitHub-Issues (standardmäßig aus, `error_reports` = `off`/`ask`/`auto`). `_Hook` (ein `logging.Handler` ab ERROR, den `attach(app)` an den Logger `sunak` hängt) übergibt jeden mit Traceback geloggten Fehler an `Reports.capture`; `__main__` leitet auch abgestürzte Hintergrund-Threads dorthin (`threading.excepthook`). `build` macht daraus Titel und Markdown (Version, System, Python, Fehler, Stacktrace nur mit Sunak-Quellzeilen und ohne Variablenwerte, `log.recent`); Die Issues sind öffentlich, darum ist `anonymize` streng: private Pfade samt Dateinamen (`<path>`), Benutzer- und Rechnername, Hosts in Adressen außer `SAFE_HOSTS` (`<host>`), `*.local`/`*.lan`, IPv4, IPv6, MAC, E-Mail, lange Zitate (`<text>`), danach `log.redact`; der Fehlertext ist auf 200 Zeichen gekürzt. `fingerprint` = SHA-1 aus Fehlerart und den letzten vier Sunak-Funktionen (ohne Zeilennummern und Text). `Reports` hält Wartende und Gesendete in `<Datenordner>/reports.json` und sendet über die GitHub-REST-API (`urllib`, Bearer-Token): ein Issue mit dem Fingerabdruck im Titel (`(fp)`; Label `auto-report`, das GitHub ohne Push-Recht still weglassen kann, darum sucht `find_issue` über die Titel der letzten 300 Issues), bei einem offenen Issue nur ein Kommentar (höchstens einer je Fehler und Tag, zehn pro Tag), bei einem geschlossenen ein neues mit Verweis; höchstens `MAX_ISSUES_PER_HOUR` (3) neue Issues pro Stunde. Das Token liegt in `settings.report_token` der Hauptdatenbank, geht nie an den Browser, in den Export oder das Log (`log.add_secret`). `issue_url` baut die vorausgefüllte Browser-Adresse (höchstens ca. 6000 Zeichen). `SUNAK_REPORT_REPO` ändert das Repository |
| `sunak/jobqueue.py` | FIFO-Warteschlange für Modellanfragen: ein `Gate` je Backend (`chat:<Anbieter-Id>`, `image`) mit `slots` Plätzen und einer Reihe wartender Anfragen; `slot(key, slots, notify, cancelled)` ist ein Kontextmanager. Wartende bekommen alle zwei Sekunden `notify(Platz)` (0 = dran); schlägt das fehl (Browser weg), verlässt die Anfrage die Reihe (`Cancelled`, eine `BrokenPipeError`, damit die bestehende Abbruchbehandlung greift). `MAX_WAIT` 900 s (`Timeout`). Wer schon einen Platz derselben Reihe hält (gleicher Thread), wartet nicht auf sich selbst. Lokale Backends haben `SUNAK_MODEL_SLOTS` (1) Plätze, Backends im Internet `REMOTE_SLOTS` (4) |
| `sunak/sdcpp.py` | Eigenes Bildprogramm: stable-diffusion.cpp aus den GitHub-Releases (passende Datei je System und Grafikkarte), Bildmodell-Katalog mit Lizenzen, Downloads mit Fortsetzen (HTTP Range), Bild erzeugen per Kommandozeile |
| `sunak/modelsearch.py` | Modellsuche in der Ollama-Bibliothek (ollama.com) und auf Hugging Face (Repositories, Dateien mit Größe, Quantisierung, Lizenz) |
| `sunak/speech.py` | Spracheingabe: Aufnahme an einen lokalen Whisper-Server weiterreichen (whisper.cpp oder OpenAI-kompatibel) |
| `sunak/knowledge.py` | Wissensbasis: Abschnitte bilden, suchen, passende Abschnitte für den Chat auswählen |
| `sunak/memory.py` | Automatisches Gedächtnis: Fakten über den Nutzer aus dem letzten Austausch, ohne Geheimnisse und Duplikate |
| `sunak/static/` | Oberfläche: `index.html`, `app.js` (gesamte Logik), `app.css` (inklusive Themes), `theme.js` (setzt das Theme vor dem ersten Zeichnen), `icons.js` (eigene Icons), `i18n.js` und `lang-de.js` (Sprachen), `login.html`, Icon, PWA-Manifest |
| `tests/` | Tests, eine Datei je Bereich (siehe Abschnitt Tests) |
| `.github/workflows/test.yml` | CI: die Tests auf Linux, macOS und Windows bei jedem Push und Pull Request |
| `install.sh`, `install.ps1` | Installer für macOS/Linux und Windows |
| `sunak/uninstall.py`, `uninstall.sh`, `uninstall.ps1` | Deinstallation (`sunak uninstall`); die Skripte finden das installierte Sunak oder laden es herunter und rufen dasselbe Python-Modul auf |
| `Dockerfile`, `docker-compose*.yml` | Container mit Ollama: nur CPU (`docker-compose.yml`), NVIDIA (`+ docker-compose.gpu.yml`) oder AMD/ROCm (`+ docker-compose.amd.yml`) |

## Datenfluss einer Chat-Nachricht

1. `app.js` legt bei Bedarf einen Chat an (`POST /api/sessions`) und schickt die Nachricht an `POST /api/chat`.
2. `Handler.chat` speichert die Nachricht und löst die Modell-ID `provider::modell` über `App.resolve` auf.
3. `App.build_messages` setzt den Verlauf zusammen: Systemprompt aus den Einstellungen, Prompt der Persona des Chats, Prompt des Chats, Notizen mit Markierung „memory“, bei eingeschalteter Wissensbasis die passenden Auszüge (siehe unten) und danach die bisherigen Nachrichten. Denkprozesse (`<think>…</think>`) werden dabei entfernt.
4. `providers.chat_stream` streamt die Antwort als Paare `("think" | "text", stück)`.
5. Der Server reicht jedes Stück sofort als NDJSON-Zeile an den Browser weiter, zum Beispiel `{"type": "text", "t": "Hallo"}`.
6. Am Ende wird die Antwort gespeichert. Der Denkprozess bleibt dabei in `<think>`-Tags eingebettet. Bricht die Verbindung ab, bleibt die Teilantwort erhalten.
7. Danach ruft `app.js` `POST /api/sessions/<id>/remember` auf (nicht im Agent-Modus, nicht nach Bildern, nicht bei ausgeschaltetem Gedächtnis). `memory.extract` lässt das Modell des Chats dauerhafte Fakten aus der letzten Frage und Antwort ziehen; neue werden Notizen mit `is_memory = 1` und `source` = Chat-ID. Ohne „Sich Dinge … selbst merken“ (`auto_memory`) geschieht das nur, wenn der Nutzer ausdrücklich „merk dir …“ schreibt. Der Browser zeigt das Gemerkte mit Rückgängig.

„Neu generieren“ und „Bearbeiten“ schicken `truncate_from` mit. Der Server löscht dann diese Nachricht und alle späteren, bevor er antwortet.

**Bilder:** Der Browser verkleinert Bilder auf höchstens 1568 Pixel Kantenlänge (größere oder lange Fotos als JPEG) und schickt sie als `images: [{name, data}]` (Base64) mit. `prepare_chat` prüft vor dem Speichern: Dateisignatur PNG, JPEG, GIF oder WebP (der Name zählt nicht), höchstens 5 MB pro Bild und 4 Bilder pro Nachricht, und ob das Modell Bilder sieht (`App.vision`: Claude ja, Ollama laut `capabilities` von `/api/show`, OpenAI-kompatibel unbekannt). Ein Modell ohne Bildverständnis bekommt eine 400-Antwort, bevor etwas gespeichert ist; der Browser legt Text und Bilder dann zurück ins Eingabefeld. Gespeichert werden die Dateien als `<data>/images/<id>.<typ>`, die Nachricht nennt sie in `meta.images`, `GET /api/images/<name>` liefert sie aus. Beim Bearbeiten schickt der Browser die Namen als `image_refs` mit. `images.attach` hängt die Bilder der letzten drei Nachrichten mit Bildern an (`message["images"] = [{type, data}]`), ältere und solche für Modelle ohne Bildverständnis werden zu einem kurzen Hinweis im Text. `providers` setzt das je Backend um: Ollama `images` (Base64), Claude Inhaltsblöcke `image` vor dem Text, OpenAI-kompatibel `image_url` mit Data-URL. Schlägt die Anfrage bei einem OpenAI-kompatiblen Backend fehl, ergänzt die Fehlermeldung den Hinweis auf Bildverständnis. Bilder ohne Nachricht (Chat gelöscht, Nachricht ersetzt) löscht `App.clean_images`, sobald sie älter als eine Stunde sind. Der Agent-Modus nimmt keine Bilder an.

## API

Alle Endpunkte liegen unter `/api/`. Schreibende Anfragen brauchen den Header `X-Requested-With: sunak`, das schützt vor CSRF. Ist ein Passwort gesetzt, ist außerdem das Cookie `sunak_token` nötig.

| Methode und Pfad | Zweck | Antwort |
|---|---|---|
| `GET /api/status` | Version, Login-Status, RAM, empfohlenes Modell | JSON |
| `GET /api/update` | Update verfügbar? (`available`, `behind`, `can_update`, einmalig `result` des letzten Updates); stößt die Prüfung im Hintergrund an | JSON |
| `GET /api/reports`, `POST /api/reports/token`, `/check`, `/send`, `/dismiss`, `/sample` | Fehlerberichte (alle nur Admin): Zustand (`mode`, `token_set`, `repo`, wartende `pending` mit Text und Browser-`url`, zuletzt `sent`), Token speichern (`{token}`, leer löscht; die Antwort enthält es nie), Zugriff prüfen, einen wartenden Bericht senden (`{id}` = Fingerabdruck; Antwort `url`, `number`, `action` = `created`/`commented`), verwerfen, Beispielbericht anlegen. `GET /api/settings` nennt Admins `reports_pending` | JSON |
| `POST /api/update/check` | Knopf „Check for updates now“ (Admin): prüft sofort, auch bei abgeschaltetem Hinweis, mit derselben Prüfung (`updates.inspect`) und aktualisiert deren Ergebnis. Antwort: `behind`, `available`, `known` (false = Prüfung nicht möglich), `version` (Version auf dem Remote), `current`, `error` (`no_clone`, `no_remote`, `no_upstream`), `can_update` | JSON |
| `POST /api/update` | Update-Knopf: startet den Hilfsprozess und beendet den Server | JSON |
| `POST /api/shutdown` | Server beenden (`sunak stop`, Knopf in Settings); von diesem Rechner ohne Login, von anderen Geräten und über einen Reverse-Proxy (`X-Forwarded-For`, `Forwarded`) nur angemeldet | JSON |
| `POST /api/login`, `POST /api/logout` | Anmelden, Abmelden | JSON |
| `GET`/`PUT /api/settings` | Einstellungen und Provider | JSON |
| `GET /api/models` | Modelle aller Provider, dazu Fehler nicht erreichbarer Provider | JSON |
| `GET /api/ollama` | Ollama-Status (installiert, läuft, Version), installierte Modelle mit Größe, Katalog mit `fits` und `gpu`, Installationsweg, GPU (`gpu`, `gpu_expected`), geladene Modelle mit GPU-Anteil (`loaded`), `gpu_warning` | JSON |
| `POST /api/ollama/start` | Lokales Ollama im Hintergrund starten | JSON |
| `POST /api/ollama/install` | Ollama per winget bzw. Homebrew installieren | NDJSON `status` |
| `POST /api/models/pull` | Ollama-Modell herunterladen; Fortschritt aller Layer summiert | NDJSON `progress` (`completed`, `total` in Bytes) |
| `POST /api/models/delete` | Ollama-Modell löschen | JSON |
| `GET`/`POST /api/sessions`, `GET`/`PATCH`/`DELETE /api/sessions/<id>` | Chats (`use_kb`, `use_web`, `persona`, Titel, Modell, Systemprompt) | JSON |
| `POST /api/sessions/<id>/remember` | Automatisches Gedächtnis ohne Body: das Modell des Chats zieht dauerhafte Fakten aus der letzten Frage und Antwort; Antwort `{added: [Notizen]}` (bei Modellfehler zusätzlich `error`) (siehe Datenfluss, Schritt 7) | JSON |
| `GET /api/search?q=` | Chats, deren Titel oder Nachrichten alle Wörter enthalten (ohne Denkprozess), mit Textausschnitt und `message_id` | JSON |
| `GET /api/sessions/<id>/export?format=md\|json` | Chat als Download; Markdown ohne Denkprozess | Datei |
| `GET /api/export` | Backup aller Chats, Dokumente, Notizen, Wissensbasis und Einstellungen, ohne API-Keys und Passwort | Datei (JSON) |
| `POST /api/agent` | Wie `/api/chat`, zusätzlich `folder` und/oder `mcp: true`; das Modell arbeitet mit Werkzeugen im Ordner (siehe Agent-Modus) und/oder mit denen der MCP-Server (siehe Werkzeuge). Mit Ordner nur wenn `agent_enabled`; von anderen Geräten nur mit Passwort | NDJSON `start` (mit `run`), `think`, `text`, `step`, `confirm`, `step_done`, `notice`, `ping`, `done` (`stopped`)/`error` |
| `POST /api/agent/confirm` | Antwort auf `confirm`: `{run, id, decision}` mit `allow`, `always` (für diesen Chat) oder `deny` | JSON |
| `GET /api/calendar` | Kalender (ohne Passwörter), CalDAV-Vorlagen, verknüpfte Mail-Konten mit passender Vorlage | JSON |
| `POST /api/calendar/sources` | `{source}`: CalDAV-Konto oder ICS-Adresse anlegen/ändern; CalDAV-Kalender werden dabei gesucht, eine ICS-Adresse einmal gelesen | JSON |
| `DELETE /api/calendar/sources/<id>` | Kalender entfernen (auf dem Server ändert sich nichts) | JSON |
| `GET /api/calendar/events?start=…&end=…` | Termine aller angezeigten Kalender im Zeitraum (ISO mit dem Offset des Geräts, höchstens etwa ein Jahr), Wiederholungen aufgelöst; Fehler je Kalender in `errors` | JSON |
| `POST /api/calendar/events` | `{source, calendar, event}` Termin anlegen | JSON |
| `PUT /api/calendar/events` | `{source, uid, href, etag, recurring, event}` Termin ändern | JSON |
| `POST /api/calendar/events/delete` | `{source, uid, href, etag}` Termin (bei Wiederholung die Serie) löschen | JSON |
| `POST /api/calendar/parse` | `{text, now, model}`: das Modell liest einen Termin aus Text, Antwort füllt das Formular | JSON |
| `GET /api/profiles` | Alle Profile (ohne PINs: `has_pin`), `current` und `need_choice`; geht auch vor der Profilwahl | JSON |
| `POST /api/profiles/select`, `POST /api/profiles/leave` | `{id, pin}` setzt das Cookie `sunak_profile`, falsche PIN: 403 nach einer Sekunde; `leave` löscht es | JSON |
| `POST /api/profiles`, `PATCH`/`DELETE /api/profiles/<id>` | Profil `{name, emoji, pin, admin}` anlegen (Admin), ändern (Admin oder das eigene, ohne Admin-Recht), löschen mit allen Daten (Admin; nicht das Hauptprofil und nicht das eigene) | JSON |
| `POST /api/mcp/test` | `{server}` (wie im Einstellungsformular, noch nicht gespeichert) einmal starten; Antwort `{tools: [{name, description}]}` | JSON |
| `POST /api/agent/cancel` | `{run}` stoppt den Agenten, ein laufender Befehl wird beendet | JSON |
| `POST /api/agent/revoke` | `{session_id}` vergisst „für diesen Chat erlauben“ | JSON |
| `POST /api/chat` | Antwort erzeugen; `use_kb` bzw. `use_web` schalten Wissensbasis bzw. Web-Suche für den Chat ein oder aus, `persona` wählt eine Persona, `images` und `image_refs` hängen Bilder an | NDJSON `start`, `sources` (nur mit Wissensbasis), `status` und `web` (nur mit Web-Suche), `think`, `text`, `done`/`error` |
| `POST /api/compare` | Ein Prompt an 2 bis 4 Modelle | NDJSON mit Modellindex `i` |
| `POST /api/research` | Web-Recherche mit Bericht | NDJSON `status`, `sources`, `text`, `done`/`error` |
| `GET`/`POST /api/documents`, `GET`/`PUT`/`DELETE /api/documents/<id>` | Dokumente | JSON |
| `POST /api/documents/ai` | KI-Bearbeitung eines Dokuments oder einer Markierung | NDJSON `text` |
| `GET /api/mail/accounts` | Konten ohne Passwort (`has_password`), dazu `presets` (Server bekannter Anbieter) | JSON |
| `POST /api/mail/accounts` | Konto `{account}` anlegen oder (gleiche `id`) ändern; leeres Passwort behält das gespeicherte | JSON |
| `DELETE /api/mail/accounts/<id>` | Konto aus Sunak entfernen (auf dem Mail-Server ändert sich nichts) | JSON |
| `POST /api/mail/test` | IMAP und SMTP mit den Daten aus dem Formular prüfen: `{imap, smtp}`, leer heißt „klappt“, sonst die Fehlermeldung | JSON |
| `GET /api/mail/<id>/folders` | Ordner mit `role` (`inbox`, `drafts`, `sent`, `archive`, `junk`, `trash`, …) | JSON |
| `GET /api/mail/<id>/messages?folder=&q=&unread=1&before=` | Neueste 40 Mails (Kopfzeilen), `before` (UID) blättert zu älteren | JSON |
| `GET /api/mail/<id>/message?folder=&uid=` | Eine Mail als Text mit Anhangsliste | JSON |
| `GET /api/mail/<id>/attachment?folder=&uid=&i=` | Anhang herunterladen (immer als Download) | Datei |
| `POST /api/mail/<id>/send` | `{to, cc, bcc, subject, body, in_reply_to, references, attachments: [{name, data}], forward: {folder, uid, attachments: [index]}}` senden; `data` ist Base64 | JSON (`saved_to`, `warning`) |
| `POST /api/mail/<id>/draft` | Gleiches Format, landet im Entwürfe-Ordner | JSON (`folder`) |
| `POST /api/mail/<id>/move` | `{folder, uids, target}`: Mails in einen anderen Ordner | JSON (`folder`) |
| `POST /api/mail/<id>/delete` | `{folder, uids, permanent}`: in den Papierkorb; endgültig nur mit `permanent: true` im Papierkorb oder ohne Papierkorb | JSON (`permanent`, `folder`) |
| `GET /api/mail/new` | Je Konto `{id, email, unseen, uidvalidity, latest (bis 5 neueste ungelesene), error}` aus dem Posteingang, nur lesend | JSON |
| `POST /api/mail/ai` | `{task: summarize\|reply\|overview, text, instruction, account, model}` | NDJSON `think`, `text`, `done`/`error` |
| `GET`/`POST /api/notes`, `PATCH`/`DELETE /api/notes/<id>` | Notizen und Gedächtnis | JSON |
| `GET /api/knowledge` | Dateien der Wissensbasis, Gesamtgröße, ob FTS5 verfügbar ist | JSON |
| `POST /api/knowledge` | Datei hinzufügen: `{name, data}` mit `data` als Base64; gleicher Name ersetzt die alte Datei | JSON |
| `GET`/`DELETE /api/knowledge/<id>` | Datei mit ausgelesenem Text, Datei entfernen | JSON |
| `GET /api/knowledge/search?q=` | Volltextsuche mit Textausschnitt | JSON |
| `GET`/`POST /api/lan` | Handy-Zugriff: Zustand, Adresse und QR-Code; `{enabled}` schaltet um (nur mit Passwort) | JSON |
| `GET /api/images/<name>` | Ein an eine Nachricht angehängtes Bild | Bild |
| `POST /api/extract` | Text einer Datei für einen Chat-Anhang (Büroklammer), gleiches Format wie oben | JSON |
| `POST /api/imagine/intent` | `{text, model}`: ist die Chat-Nachricht ein Bildwunsch? Antwort `{image, subject, via}`; `via` ist `rules` oder `model` (bei `maybe`/`no` wird das Chatmodell gefragt, wenn Bilder eingerichtet sind und `ai_image_detect` an ist; `quick` fragt es nie) | JSON |
| `POST /api/imagine` | `{session_id, prompt, negative, aspect (square\|portrait\|landscape\|auto), seed, improve, model, fallback}`: Bild mit dem eingestellten Programm erzeugen; Beschreibung und Bild werden als Nachrichten gespeichert. Mit `improve` ist `prompt` die Bitte des Nutzers in eigenen Worten: das Chatmodell `model` macht daraus einen Prompt für das Bildmodell (`imagegen.improve_messages`/`clean_prompt`; bei Fehler oder ohne Modell gilt `fallback`, die schlichte Beschreibung), `aspect: auto` liest das Format aus dem Text (`aspect_from_text`). Verbindung schließen bricht im Programm ab | NDJSON `start`, `status` (`t`), `queued` (`position`, 0 = dran), `prompt` (der Prompt für das Bildmodell), `progress` (`p` 0 bis 1 oder `null`), `done` (`image`, `info`)/`error` |
| `GET /api/imagegen/local` | Eigenes Bildprogramm (`engine.installed`, `tag`, `kind`) und Bildmodelle mit `installed`, `partial`, `downloading`, `fits`, `gpu`, Lizenz | JSON |
| `GET /api/imagegen/engine` | Passende stable-diffusion.cpp-Dateien der neuesten Version, beste zuerst (Admin) | JSON |
| `POST /api/imagegen/engine/install` | `{name}` aus dieser Liste herunterladen und entpacken (Admin); eine Adresse vom Browser wird nie angenommen | NDJSON `progress` (`completed`, `total`), `done`/`error` |
| `POST /api/imagegen/engine/remove` | Bildprogramm löschen, Modelle bleiben (Admin) | JSON |
| `POST /api/imagegen/models/pull` | `{id}` aus dem Katalog oder `{repo, path}` aus der Suche herunterladen, Abbrechen = Pause (Admin) | NDJSON wie oben |
| `POST /api/imagegen/models/delete` | `{id}` Bildmodell löschen (Admin) | JSON |
| `GET /api/models/search?q=&kind=chat\|image` | Ollama-Bibliothek und Hugging Face; nicht erreichbare Seiten stehen in `unreachable` | JSON |
| `GET /api/models/files?repo=&kind=` | Dateien eines Hugging-Face-Repositorys mit Größe, Quantisierung, Ollama-Name (`hf.co/<repo>:<quant>`), Lizenz, `gated` | JSON |
| `POST /api/imagegen/test` | `{type, url}` aus dem Formular: Modelle des Programms (nur Admin-Profile) | JSON |
| `POST /api/transcribe` | Spracheingabe: `{audio}` (WAV als Base64, optional `language`) an den Whisper-Server, Antwort `{text}` | JSON |

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

## GPU

Sunak rechnet nicht selbst; Ollama nutzt die GPU von sich aus (CUDA, ROCm, Metal). Sunak sorgt dafür, dass man sieht, ob das klappt, und passt die Empfehlungen an.

- **Erkennung** (`sunak/gpu.py`): NVIDIA über `nvidia-smi` (Name, VRAM; fehlt der Treiber, findet Linux die Karte trotzdem über `/sys/class/drm` und Sunak rät zum Treiber), AMD und Intel unter Linux über `/sys/class/drm` (`mem_info_vram_total`), unter Windows über die Registry (`HardwareInformation.qwMemorySize` der Grafikadapter, ohne Zusatzprogramme), Apple Silicon über `platform.machine()`. Nutzbar für Ollama gilt eine NVIDIA- oder AMD-Karte mit Treiber und mindestens 3 GB VRAM oder Apple Silicon (gemeinsamer Speicher). Intel-Grafik und kleine integrierte AMD-GPUs zählen nicht. Die Erkennung läuft einmal beim Start im Hintergrund (`App.gpu`); jeder Fehler heißt einfach „keine GPU“.
- **Nutzung prüfen:** `GET /api/ollama` fragt zusätzlich `/api/ps` ab. Pro geladenem Modell steht dort `size_vram`, daraus wird der GPU-Anteil. Liegt kein Byte auf der GPU, obwohl eine nutzbare GPU da ist, liefert `gpu.cpu_warning` einen Hilfetext je Hersteller.
- **Nur lokal:** Die GPU dieses Rechners zählt nur, wenn der Ollama-Provider auf `localhost` zeigt. Bei Docker läuft Ollama in einem eigenen Container; die GPU-Compose-Dateien setzen deshalb `SUNAK_GPU=nvidia|amd` im Sunak-Container, damit die Warnung auch dort greift.
- **Empfehlungen:** Der Katalog markiert Modelle mit `gpu`, die komplett in den VRAM passen (Größe × 1,2 + 1 GB), auf Apple Silicon gilt die RAM-Regel. `recommend()` nimmt ein größeres Startmodell, wenn es ganz in den VRAM passt, aber nie ein kleineres als nach RAM.
- **Installer und Kommandozeile:** `sunak gpu` gibt das Ergebnis als Text aus; `install.sh` und `install.ps1` zeigen es vor der Ollama-Installation an. Den GPU-Teil (CUDA- bzw. ROCm-Bibliotheken) bringt der offizielle Ollama-Installer selbst mit.

## Agent-Modus

Agentisches Coding: Das Modell arbeitet in einer Schleife mit Werkzeugen in einem Projektordner, den der Nutzer im Chat einträgt (`sunak/agent.py`). Standardmäßig aus (`agent_enabled`).

- **Werkzeuge:** `list_files`, `read_file` (höchstens 2000 Zeilen pro Aufruf, Dateien bis 2 MB, nur UTF-8-Text), `search` (Text oder regulärer Ausdruck, überspringt `.git`, `node_modules` und ähnliche), `write_file`, `edit_file` (exakter Text, muss eindeutig sein; Windows-Zeilenenden bleiben erhalten), `run_command`. Lesen läuft ohne Rückfrage; Schreiben, Bearbeiten und Befehle brauchen eine Freigabe.
- **Ordnergrenze:** Jeder Pfad wird mit `os.path.realpath` aufgelöst (`..`, absolute Pfade, Symlinks) und muss danach im Ordner liegen. Ordner-Symlinks werden beim Auflisten und Suchen nicht verfolgt. Als Ordner verboten sind ein Laufwerk, der ganze Home-Ordner und jeder Ordner, der Sunaks Datenordner enthält (API-Keys) oder darin liegt. Vor dem Schreiben prüft Sunak, ob sich die Datei seit der Vorschau geändert hat.
- **Befehle:** Shell (`sh`, unter Windows `cmd.exe`) im Projektordner, ohne Eingabe (`stdin` leer, `GIT_TERMINAL_PROMPT=0`), ohne `SUNAK_PASSWORD` in der Umgebung. Zeitlimit `agent_timeout` (Standard 120 s), danach oder bei Stop wird die ganze Prozessgruppe beendet (`killpg` bzw. `taskkill /T`). Von der Ausgabe bleiben die ersten 20 KB und die letzten 30 KB. Befehle laufen mit den Rechten des Nutzers und sind nicht abgeschottet; deshalb die Freigabe und der Warnhinweis in Settings.
- **Freigaben:** Vor dem Schreiben oder Ausführen sendet der Server `confirm` mit Diff bzw. Befehl und wartet (alle 15 s ein `ping`, nach 30 Minuten gilt „Deny“). `always` erlaubt diese Art (Schreiben oder Befehle) für den Chat und Ordner, bis Sunak neu startet oder „Ask again“ geklickt wird; das liegt nur im Speicher (`agent.Registry`). Abgelehnte Schritte gehen als Fehler an das Modell zurück.
- **Tool-Calling je Backend:** Claude über `tools` der Messages API; Denkblöcke (mit Signatur), Text und `tool_use` gehen unverändert zurück, Ergebnisse als `tool_result`. Auf `api.anthropic.com` ist `eager_input_streaming` an; die Argumente werden erst nach vollständigem Empfang streng als JSON gelesen und geprüft. Ollama über `tools` in `/api/chat`, Ergebnisse als Rolle `tool` mit `tool_name`. OpenAI-kompatibel über `tools`, Teilstücke von `tool_calls` werden pro `index` zusammengesetzt, Ergebnisse mit `tool_call_id`.
- **Textprotokoll:** Meldet Ollama „does not support tools“ (oder lehnt eine OpenAI-kompatible API den Parameter `tools` mit einem Fehler ab), schaltet Sunak für diese Antwort auf ein Textprotokoll um und zeigt einen Hinweis. Das Modell schreibt dann einen Block ` ```tool {"tool": …, "args": …}`. Sunak liest ihn mit `json.JSONDecoder.raw_decode`, bricht die Generierung nach dem ersten vollständigen Block ab (damit das Modell kein Ergebnis erfindet), zeigt den Block nicht als Text und schickt das Ergebnis als Nachricht `[Result of …]`.
- **Grenzen:** höchstens `agent_max_steps` Runden pro Antwort (Standard 30; eine Runde ist eine Modellantwort mit ihren Werkzeugaufrufen), Ergebnisse höchstens 30 000 Zeichen an das Modell.
- **Speichern:** Die Antwort wird mit ihren Teilen gespeichert: `messages.meta.agent = {folder, parts}`, wobei `parts` Textabschnitte und Schritte (Werkzeug, Titel, Status `done`/`error`/`denied`/`stopped`, Diff, gekürzte Ausgabe) in Reihenfolge enthält. `content` enthält nur den Text; spätere Anfragen sehen also die Antworten, aber nicht die alten Werkzeugergebnisse.
- **Zugriff:** Ein Chat mit Projektordner verlangt `agent_enabled`. Kommt eine Anfrage nicht direkt von diesem Rechner (oder über einen Reverse-Proxy), ist außerdem ein Passwort nötig, auch für Freigaben.
- **Oberfläche:** Der Terminal-Knopf neben dem Eingabefeld (nur sichtbar, wenn eingeschaltet) und die Ordnerzeile darüber; Ordner und Schalter merkt sich der Browser (`localStorage`). `runAgent` in `app.js` zeigt Text und Schritte live, Freigaben als Karte mit Diff bzw. Befehl. Stop schickt `/api/agent/cancel` und bricht den Stream ab.

## Kalender

`sunak/cal.py` liest und schreibt iCalendar (RFC 5545) und spricht CalDAV (RFC 4791), nur mit der Standardbibliothek.

- **Quellen:** Sunaks eigener Kalender (Tabelle `calendar_events`, ein iCalendar-Text je Termin), CalDAV-Konten und ICS-Adressen (`settings.calendars`). `GET /api/calendar/events` lädt alle angezeigten Kalender parallel; ein Kalender, der nicht antwortet, erscheint als Hinweis, die anderen trotzdem.
- **Zeiten:** Zeitzonen kommen aus der Zeitzonendatenbank des Systems (`zoneinfo`, auch Windows-Namen wie „W. Europe Standard Time“) oder, wo sie fehlt (Windows ohne `tzdata`), aus dem `VTIMEZONE` der Datei selbst. Termine gehen als UTC an den Browser und werden in der Zeitzone des Geräts angezeigt; ganztägige als Datum mit exklusivem Ende. Neue Termine werden in UTC geschrieben. Der Browser schickt den Zeitraum mit seinem Offset, so stimmen die Tage auch am Handy in einer anderen Zeitzone.
- **Wiederholungen:** `FREQ` DAILY/WEEKLY/MONTHLY/YEARLY mit `INTERVAL`, `COUNT`, `UNTIL`, `BYDAY` (auch „2. Dienstag“, „letzter Freitag“), `BYMONTHDAY` (auch negativ), `BYMONTH`, `BYSETPOS`, dazu `EXDATE`, `RDATE` und verschobene oder abgesagte einzelne Termine (`RECURRENCE-ID`). Nicht unterstützt: `BYWEEKNO`, `BYYEARDAY`, stündliche Regeln.
- **CalDAV:** Beim Speichern eines Kontos sucht Sunak `current-user-principal` → `calendar-home-set` → Kalender (`PROPFIND`), auch über `/.well-known/caldav`; Aufgabenlisten (nur `VTODO`) werden übergangen. Weiterleitungen werden mit Methode gefolgt, die Anmeldung geht nur innerhalb derselben Domain mit (iCloud antwortet von `pNN-caldav.icloud.com`). Termine kommen per `REPORT calendar-query` mit Zeitraum; Anlegen mit `PUT` und `If-None-Match: *`, Ändern und Löschen mit `If-Match` (ETag), damit nichts überschrieben wird, das inzwischen woanders geändert wurde. Beim Ändern bleibt alles, was Sunak nicht bearbeitet (Erinnerungen, Gäste), erhalten; bei Serien ändern sich nur Titel, Ort und Notizen. Ein Termin-Link muss in einem Kalender des Kontos liegen.
- **Anmeldung:** eigenes Passwort oder das eines verknüpften Mail-Kontos (`mail_account`, für iCloud, GMX, WEB.DE und Yahoo gilt dasselbe App-Passwort). Passwörter gehen nie an den Browser; ein leeres Feld behält das gespeicherte, aber nur bei gleicher Adresse und gleichem Benutzer. Google und Outlook.com haben kein CalDAV mit Passwort; dafür gibt es den Hinweis auf ihre ICS-Adresse.
- **ICS-Abos:** `GET` der Adresse (`webcal://` wird zu `https://`), 5 Minuten zwischengespeichert, nur lesen.
- **Termin aus Text:** `POST /api/calendar/parse` gibt dem Modell Datum, Uhrzeit und Offset des Geräts und verlangt ein JSON-Objekt; `parse_answer` prüft es. Das Ergebnis füllt nur das Formular, gespeichert wird nach dem Klick. In der Mail-Ansicht schickt „Add to calendar“ die Mail mit ihrem Datum.
- **Oberfläche:** Monatsansicht (Montag zuerst), rechts der gewählte Tag, das Formular und die Liste der Kalender zum Ein- und Ausblenden (pro Gerät in `localStorage`). Am Handy werden Termine zu Punkten.

## Werkzeuge (MCP)

`sunak/mcp.py` ist ein MCP-Client (Protokollversion `2025-06-18`) nur mit der Standardbibliothek. Sunak nutzt von MCP nur Werkzeuge (`tools/list`, `tools/call`).

- **Servertypen:** `stdio`: Sunak startet den Befehl (`shutil.which`, also auch `npx.cmd` unter Windows) im Home-Ordner mit den gespeicherten Umgebungsvariablen und spricht JSON-RPC zeilenweise über stdin/stdout; Zeilen, die kein JSON sind, werden übersprungen, `ping` und `roots/list` des Servers beantwortet, die Fehlerausgabe (letzte 2000 Zeichen) erscheint in Meldungen. `http`: Streamable HTTP, JSON-RPC per POST an eine Adresse, Antwort als JSON oder Server-Sent Events, `Mcp-Session-Id` und `MCP-Protocol-Version` werden mitgeschickt, optional ein Bearer-Token; beim Beenden `DELETE`.
- **Lebensdauer:** `App.mcp` (`mcp.Manager`) startet die eingeschalteten Server, wenn ein Chat mit eingeschalteten Werkzeugen sie zum ersten Mal braucht (parallel, höchstens 60 s, weil `npx -y`/`uvx` beim ersten Mal herunterladen), und lässt sie laufen. Geänderte oder entfernte Server werden beim Speichern beendet, abgestürzte beim nächsten Chat neu gestartet, alle beim Beenden von Sunak.
- **Im Chat:** `POST /api/agent` mit `mcp: true` (ohne Ordner nur MCP-Werkzeuge, mit Ordner zusätzlich die Agent-Werkzeuge). `agent.AgentRun` bietet sie dem Modell im Format des Backends an; der Name ist `<Server>__<Werkzeug>` (höchstens 64 Zeichen aus `[a-zA-Z0-9_-]`, längere mit Hash), die Beschreibung und das `inputSchema` kommen vom Server. Jeder Aufruf braucht eine Freigabe (`confirm` mit `kind: "tool:<Name>"`, `server`, `mcp_tool` und der Eingabe als JSON); „für diesen Chat erlauben“ gilt pro Werkzeug. Pflichtargumente werden vorher geprüft, `isError` und Verbindungsfehler gehen als Fehler an das Modell, Stop schickt `notifications/cancelled`. Bilder und Audio aus Ergebnissen werden nur als Platzhalter weitergegeben.
- **Einstellungen:** `settings.mcp_servers` = `[{id, name, type, enabled, command, env | url, token}]`, geprüft von `mcp.clean`. Der Browser bekommt nur `mcp.public`: statt der Werte `env_keys` bzw. `has_token`. Schickt er einen Server ohne `env`/`token` zurück, bleiben die gespeicherten, aber nur bei gleichem Befehl bzw. gleicher Adresse (sonst könnten sie an ein anderes Programm gehen).
- **Zugriff:** Server vom Typ `stdio` führen Programme mit den Rechten des Nutzers aus. Deshalb verlangen Ändern von `mcp_servers`, `/api/mcp/test`, Chats mit MCP und Freigaben von anderen Geräten (oder über einen Reverse-Proxy) ein gesetztes Passwort.
- **Oberfläche:** Der Stecker-Knopf neben dem Eingabefeld erscheint, sobald ein Server eingeschaltet ist; der Schalter liegt in `localStorage` (`sunak-mcp`). Settings → Tools (MCP) mit Karten je Server, „Test“ und Vorlagen (Dateien, Webseiten lesen, Uhrzeit, Gedächtnis). Bilder im Chat werden bei Werkzeugen wie im Agent-Modus abgelehnt.

## Web-Suche im Chat

Schalter pro Chat wie die Wissensbasis (`sessions.use_web`, im Request `use_web`). Ist er an, ruft `Handler.chat` nach dem `start`-Ereignis `web_search` auf:

1. Suchanfrage: bei der ersten Frage der Text selbst (ohne angehängte Dateien), bei Folgefragen formuliert das Modell aus den letzten fünf Nachrichten eine kurze Suchanfrage (`temperature` 0), damit „und in Hamburg?“ funktioniert.
2. `research.gather` sucht (DuckDuckGo bzw. `SEARXNG_URL`) und liest die Treffer parallel; übrig bleiben bis zu vier Seiten mit mehr als 200 Zeichen, gekürzt auf je 3000 Zeichen.
3. `research.web_context` setzt sie nummeriert mit Datum in den Systemprompt, mit dem Hinweis, Quellen als `[1]` zu zitieren und Text darin als Daten Dritter, nicht als Anweisung zu behandeln.
4. Der Browser bekommt `status`-Ereignisse („Searching the web: …“) und `web` mit Anfrage und Quellen; gespeichert wird beides in `messages.meta.web`.

Schlägt die Suche fehl oder findet sie nichts Lesbares, antwortet das Modell ohne Web und der Browser sieht den Grund als Status.

## Deep Research

1. Das Modell schlägt bis zu drei Suchanfragen vor.
2. `research.search` sucht über DuckDuckGo, das ohne Schlüssel auskommt. Ist `SEARXNG_URL` gesetzt, wird stattdessen SearXNG verwendet.
3. Bis zu fünf Seiten werden geladen und in Text umgewandelt, jeweils höchstens 6000 Zeichen.
4. Das Modell schreibt einen Markdown-Bericht mit Quellenverweisen wie `[1]`.

## E-Mail

`sunak/mail.py` nutzt nur `imaplib`, `smtplib` und `email`. Jede Anfrage öffnet eine eigene Verbindung und schließt sie wieder; es gibt keinen Hintergrunddienst.

- **Konten** liegen in der Einstellung `mail_accounts`: `{id, email, name, username, password, imap_host, imap_port, imap_security, smtp_host, smtp_port, smtp_security, save_sent}`, `*_security` ist `ssl`, `starttls` oder `none`. `none` und das Akzeptieren selbst signierter Zertifikate gibt es nur für `localhost`/Loopback (z. B. Proton Mail Bridge). `mail.clean_account` prüft alles; ein leeres Passwort übernimmt das gespeicherte nur bei gleichem Benutzernamen und gleichen Servern, damit es nie an einen anderen Server geht. `PRESETS` enthält die Server bekannter Anbieter samt Domains (das Frontend wählt die Vorlage anhand der Adresse) und Hinweistext zum App-Passwort.
- **Passwörter** verlassen den Server nie: `mail.public` entfernt sie, `/api/export` ebenso. Fehlermeldungen laufen durch `_safe`, das ein Passwort sicherheitshalber ersetzt. Nicht-ASCII-Passwörter gehen per `AUTHENTICATE PLAIN` (IMAP) bzw. eigenem `AUTH PLAIN` (SMTP) in UTF-8, weil `LOGIN` und `smtplib.login` nur ASCII können.
- **Nur lesen:** Ordner werden mit `EXAMINE` (`select(readonly=True)`) geöffnet und Mails mit `BODY.PEEK` geholt, so bleibt `\Seen` unverändert. Die Liste holt nur `FROM TO SUBJECT DATE`, Flags und Größe; Suche per `UID SEARCH TEXT` (jedes Wort muss vorkommen), Text mit Umlauten als UTF-8-Literal mit `CHARSET UTF-8`.
- **Mail lesen:** höchstens 10 MB pro Mail, Text bevorzugt aus `text/plain`, sonst wird HTML mit `research.html_to_text` in Text umgewandelt (Skripte fallen weg, nichts wird nachgeladen). Ordnernamen kommen in IMAPs modifiziertem UTF-7 und werden mit `utf7_decode` lesbar gemacht. Die Rolle eines Ordners stammt aus den Special-Use-Flags (RFC 6154), sonst aus dem Namen („Gesendet“, „Entwürfe“, …).
- **Schreiben:** `build_message` baut eine `EmailMessage` (Adressen geprüft, Zeilenumbrüche in Kopfzeilen entfernt, `In-Reply-To`/`References` für Antworten). `attachments` sammelt die Dateien: hochgeladene (Base64, Name bereinigt, MIME-Typ aus der Endung) und beim Weiterleiten die gewählten Anhänge des Originals, die der Server mit `_original_attachments` vollständig (bis 48 MB statt der 10 MB fürs Anzeigen) aus dem Postfach holt. Zusammen höchstens `MAX_ATTACH` (17 MB). `send` schickt per SMTP und legt bei `save_sent` eine Kopie mit `APPEND` in den Gesendet-Ordner (Gmail und Outlook machen das selbst, daher dort aus). Scheitert nur die Kopie, ist die Mail trotzdem verschickt und es gibt eine Warnung. `save_draft` legt die Mail mit `\Draft` in den Entwürfe-Ordner.
- **Verschieben und Löschen:** einzige schreibende IMAP-Befehle außer `APPEND`. `_move` öffnet den Ordner mit `SELECT` (schreibend) und nimmt `UID MOVE` (RFC 6851), wenn der Server es kann; sonst `UID COPY`, `\Deleted` setzen und `UID EXPUNGE` (UIDPLUS), ohne UIDPLUS ein normales `EXPUNGE` wie andere Mail-Programme. `delete` verschiebt in den Ordner mit der Rolle `trash`; endgültig (`\Deleted` + Expunge) nur aus dem Papierkorb oder bei Konten ohne. Ziel- und Quellordner müssen in der Ordnerliste stehen. Gmail bildet Labels als Ordner ab: `MOVE` tauscht das Label, der Papierkorb ist `[Gmail]/Trash` mit `\Trash`.
- **Neue Mail:** `check_new` öffnet den Posteingang lesend, sucht `UNSEEN` und gibt Anzahl, `UIDVALIDITY` und die fünf neuesten zurück. Der Browser fragt `/api/mail/new` alle 2 Minuten (Einstellung `mail_notify`, je Profil), merkt sich je Konto `UIDVALIDITY` und die höchste gemeldete UID in `localStorage` (`sunak-mail-seen`); der erste Abruf setzt nur diese Grenze. Neuere UIDs ergeben einen Hinweis mit „Open“ und, wenn erlaubt und die Seite im Hintergrund ist, eine `Notification`. Die Zahl am Knopf Mail ist die Summe der ungelesenen.
- **Selbsttest:** `sunak/mailtest.py` liest die Konten aus den Datenbanken aller Profile (nur lesend) oder fragt Adresse und App-Passwort mit `getpass` ab (`--new`, Server aus `PRESETS`). Jede Testmail hat `sunak-selftest-<zufall>` im Betreff; `mail.find` sucht per `UID SEARCH SUBJECT` und prüft jeden Treffer selbst, weil Gmails Suche Wörter unscharf vergleicht. Aufräumen: alle Ordner außer dem Papierkorb in den Papierkorb, dort endgültig löschen (mehrmals, weil Gmail verzögert). Ausgabe ✓/✗/! je Schritt, Exit-Code 0 nur ohne ✗.
- **KI:** `ai_messages` baut die Prompts für `summarize`, `reply` und `overview`. Die Mail steht in `<email>`-Tags, und der Systemprompt sagt, dass ihr Inhalt Daten und keine Anweisungen sind. Gedächtnis-Notizen werden mitgegeben (z. B. der eigene Name für die Grußformel). Die Antwort wird nur ins Formular gestreamt. „Ask in chat“ hängt die Mail im Browser als Datei-Anhang namens „E-Mail: Betreff“ an einen neuen Chat, genau wie eine Datei über die Büroklammer.
- **Frontend:** Abschnitt „Mail“ in `app.js`: Konto- und Ordnerauswahl, Liste mit „Load older“, Leseansicht mit „Move to…“ und Delete (Rückfrage, im Papierkorb „endgültig?“), Formular für neue Mail, Antwort, Weiterleiten, Anhänge als Chips (`renderComposeFiles`; eigene Dateien als Base64, weitergeleitete nur als Index). Senden fragt vorher nach. Neue Mail: `checkNewMail`. Die Einrichtung steht in Settings → Mail accounts (`editMailAccount`).

## Wissensbasis

Hochgeladene Dateien gehen den Weg `extract.extract_text` → `knowledge.chunk` → `DB.kb_add`.

- **Textauslese** nur mit der Standardbibliothek. Word, OpenDocument und PowerPoint sind ZIP-Archive mit XML und werden mit `zipfile` und `ElementTree` gelesen. Für PDF gibt es einen eigenen kleinen Leser: Er findet alle Objekte (auch in Objekt-Streams von PDF 1.5+), entpackt Flate-, ASCII85- und ASCIIHex-Streams, folgt dem Seitenbaum mit geerbten Ressourcen und übersetzt Zeichen über die `ToUnicode`-CMap des Fonts, sonst über WinAnsi bzw. MacRoman. Leerzeichen und Zeilenumbrüche ergeben sich aus den Textpositionen. Formular-XObjects werden mitgelesen.
- **Grenzen:** Gescannte PDFs ohne Textebene (das bräuchte Texterkennung) und verschlüsselte PDFs liefern eine verständliche Fehlermeldung. Bei Fonts ohne `ToUnicode`, die nur Glyph-Nummern enthalten, bleibt der Text leer. Mehrspaltige Layouts werden in der Reihenfolge des Content-Streams gelesen.
- **Abschnitte** von etwa 1000 Zeichen an Absatz-, Zeilen- oder Satzgrenzen.
- **Suche:** SQLite-FTS5 (`kb_fts`, Rowid = `kb_chunks.id`, Umlaute und Akzente werden beim Vergleich ignoriert) mit bm25-Ranking. Die Suchwörter stammen aus den letzten beiden Fragen ohne Stoppwörter (deutsch und englisch), Wörter ab 4 Buchstaben auch als Präfix, damit „Handbuch“ auch „Handbuchs“ findet. Fehlt FTS5 im SQLite, rechnet `knowledge._scan` ein einfaches TF-IDF in Python.
- **Prompt:** Ist die ganze Wissensbasis höchstens 8000 Zeichen groß, bekommt das Modell alles (dann klappen auch Fragen wie „fasse das zusammen“). Sonst bekommt es bis zu 6 passende Abschnitte mit höchstens 7000 Zeichen. Die Abschnitte stehen mit Dateinamen im Systemprompt, und das Modell soll die Datei in eckigen Klammern nennen.
- **Quellen:** Die verwendeten Dateien werden als `sources`-Ereignis gesendet und in `messages.meta` gespeichert, damit sie auch später unter der Antwort stehen.

## Start, Autostart und Desktop-Icon

- **Nur ein Sunak:** Vor dem Start fragt `__main__` die Ports 7000 bis 7009 nach einem laufenden Sunak ab. Antwortet eines, wird nur der Browser geöffnet. Deshalb kann das Desktop-Icon beliebig oft angeklickt werden.
- **Beenden:** `sunak stop` schickt `POST /api/shutdown` an das laufende Sunak. Wer Sunak über das Icon ohne Terminal gestartet hat, beendet es in Settings mit ⏻ Stop Sunak.
- **Autostart** (`sunak autostart on`) startet Sunak beim Anmelden mit `--no-browser` im Hintergrund:

| System | Datei |
|---|---|
| Linux | `~/.config/autostart/sunak.desktop` (XDG-Autostart, funktioniert in GNOME, KDE, Xfce usw.) |
| macOS | `~/Library/LaunchAgents/dev.sunak.plist` (LaunchAgent mit `RunAtLoad`, Log in `~/.sunak/sunak.log`) |
| Windows | `Sunak.vbs` im Autostart-Ordner; startet `pythonw` ohne Konsolenfenster |

- **Desktop-Icon** (`sunak shortcut`): Linux legt `sunak.desktop` ins App-Menü und auf den Desktop (bei GNOME als vertrauenswürdig markiert), macOS ein kleines `Sunak.app` in `~/Applications` mit Verknüpfung auf dem Desktop, Windows `Sunak.lnk` auf Desktop und im Startmenü, das ein verstecktes `Sunak.vbs` startet.
- Alle Einträge rufen den aktuellen Python-Interpreter mit `-m sunak` und setzen `PYTHONPATH` auf den Installationsordner, daher funktionieren sie auch ohne `sunak`-Befehl im `PATH`.
- `sunak uninstall [--yes] [--purge]` (`sunak/uninstall.py`): beendet ein laufendes Sunak, entfernt Autostart, Icons (nur eigene: `.desktop`-Dateien mit `-m sunak`, das `Sunak.app`-Symlink, `Sunak.lnk`), den Launcher (nur mit der Markierung „Sunak launcher“), `app`, `source` bzw. unter Windows `%LOCALAPPDATA%\sunak` und den PATH-Eintrag (Zeile mit `# sunak PATH` in `.bashrc`, `.bash_profile`, `.zshrc`, `.profile`; unter Windows der Eintrag im Benutzer-`Path` der Registry, Typ bleibt erhalten). Docker-Compose-Projekte mit einem Dienst `sunak` werden über ihre Labels gefunden; der Sunak-Container (mit dem gebauten Image) nur nach Rückfrage oder mit `--yes`, der Ollama-Container (mit Image) nur nach eigener Rückfrage oder mit `--with-ollama`. Daten (`SUNAK_DATA` bzw. `~/.sunak`, bei Docker `data/` im Projektordner ohne `data/ollama`) löscht nur `--purge` oder ein ausdrückliches `y`. Ollama selbst (`ollama_install` erkennt den Weg: Inno-Deinstaller `unins000.exe` oder winget unter Windows, Homebrew-Cask, -Formel oder App unter macOS, offizielles `install.sh` mit systemd-Dienst, Snap oder Distributionspaket unter Linux) entfernt nur ein `y` oder `--with-ollama`; Fehlschläge harmloser Schritte (Dienst stoppen, Benutzer löschen) zählen nicht. Modelle (`OLLAMA_MODELS` bzw. `~/.ollama/models`, `/usr/share/ollama/.ollama/models`, `data/ollama` bei Docker) löscht nur ein `y` oder `--with-models`, nicht `--purge` und nicht `--with-ollama`. Ohne Terminal gilt bei jeder Frage die Vorgabe, also nichts löschen. Home-Ordner, darüberliegende Ordner und Laufwerkswurzeln löscht es nie. Der Windows-Launcher ruft `uninstall` in einem Block mit `exit /b` auf, weil `cmd` die gelöschte `sunak.cmd` sonst weiterlesen würde.
- `sunak update` holt den neuen Code: Wurde aus einem Git-Klon installiert, merkt sich der Installer dessen Pfad (`~/.sunak/source`, Windows `%LOCALAPPDATA%\sunak\source.txt`), und das Update macht dort `git pull` und installiert neu. Für das öffentliche Repository sind dafür keine Zugangsdaten nötig (`git fetch` und `pull` laufen anonym über https, `GIT_TERMINAL_PROMPT=0` verhindert Rückfragen), ein privater Fork funktioniert mit den Zugangsdaten des Klons. Sonst wird der aktuelle Installer heruntergeladen. Das Update zeigt alte und neue Version und beendet ein laufendes Sunak, damit der nächste Start die neue Version verwendet.


## Update-Hinweis

- **Prüfung** (`sunak/updates.py`, `App.check_updates`): beim Start und danach höchstens alle 6 Stunden (nach einem Fehlschlag erneut nach 30 Minuten) läuft im Hintergrund `git fetch` im Klon, aus dem Sunak stammt: der App-Ordner selbst, wenn er ein Git-Klon ist, sonst der vom Installer gemerkte Klon (`~/.sunak/source`, Windows `source.txt`). Gezählt werden die Commits zwischen der installierten Version und dem Upstream-Branch (`git rev-list --count <installiert>..@{u}`). Die installierte Version schreibt der Installer nach `.commit` im App-Ordner, daher fällt auch ein Klon auf, der schon gepullt, aber noch nicht neu installiert wurde.
- **Still scheitern:** ohne git, ohne Netz, ohne Klon, ohne Upstream-Branch oder bei Passwortabfragen (`GIT_TERMINAL_PROMPT=0`, kein Terminal, unter Windows `GCM_INTERACTIVE=never`) gibt es einfach keinen Hinweis.
- **Oberfläche:** `GET /api/update` beim Laden, nach 20 Sekunden und dann stündlich. Gibt es neue Commits, erscheint oben in der Seitenleiste „Update available“ mit dem Knopf **Update**. Abschaltbar in Settings → Updates (`check_updates`); der Knopf „Check for updates now“ dort ruft `POST /api/update/check` und nennt bei einem Fehlschlag den Grund.
- **Update-Knopf:** `POST /api/update` startet `python -m sunak.updates` als eigenständigen Prozess und beendet den Server. Der Hilfsprozess wartet, bis der alte Server weg ist, führt `git pull --ff-only` (App-Ordner ist ein Klon) oder den installierten Befehl `sunak update` aus, schreibt das Ergebnis nach `update-result.json` im Datenordner, protokolliert nach `update.log` und startet Sunak mit gleichem Host, Port und Datenordner neu. Die Seite erkennt den Neustart an der geänderten `instance` in `/api/status`, lädt neu und zeigt das Ergebnis einmal an. Ohne Klick wird nie etwas installiert.

## Datenhaltung

Alle Daten liegen in einer SQLite-Datei: `~/.sunak/sunak.db`, der Ordner lässt sich über `SUNAK_DATA` ändern.

| Tabelle | Inhalt |
|---|---|
| `sessions` | Chats: Titel, Modell, eigener Systemprompt, `use_kb` (Wissensbasis an/aus), `use_web` (Web-Suche an/aus), `persona` (Id) |
| `messages` | Nachrichten der Chats (werden mit dem Chat gelöscht); `meta` (JSON) enthält z. B. die Quellen oder die Namen angehängter Bilder (Dateien in `images/` neben der Datenbank) |
| `kb_files`, `kb_chunks`, `kb_fts` | Wissensbasis: Dateien, ihre Textabschnitte und der Volltextindex |
| `documents` | Markdown-Dokumente |
| `notes` | Notizen; `is_memory = 1` bedeutet „im Gedächtnis“, `source` ist die Chat-ID, wenn Sunak sie selbst angelegt hat |
| `settings` | Schlüssel-Wert-Paare als JSON: `prefs` (u. a. Theme, Sprache, Bildgenerierung), `providers`, `personas` (fehlt der Eintrag, gelten `DEFAULT_PERSONAS`), `mail_accounts`, `calendars`, `mcp_servers`, `report_token` (GitHub-Token für Fehlerberichte, nur Hauptdatenbank), `profiles` (nur Hauptdatenbank), `lan_access`, `password_hash`, `secret` |
| `calendar_events` | Sunaks eigener Kalender: `uid`, iCalendar-Text, Änderungszeit |

Jedes weitere Profil hat eine eigene Datei mit denselben Tabellen unter `profiles/<id>/` (siehe Profile).

Spalten, die später dazukamen, legt `DB.__init__` beim Start an (`MIGRATIONS`), ältere Datenbanken funktionieren also weiter. Die hochgeladenen Originaldateien werden nicht aufbewahrt, nur ihr Text.

Passwörter werden mit PBKDF2-SHA256 und Salt gespeichert. Das Login-Cookie ist ein HMAC aus dem Geheimnis der Installation und dem Passwort-Hash. Wird das Passwort geändert, sind daher alle Sitzungen abgemeldet.

## Profile

Ein Profil ist eine eigene Datenbank: das Hauptprofil (`default`) nutzt `~/.sunak/sunak.db`, jedes weitere `~/.sunak/profiles/<id>/sunak.db` mit eigenem `images/`-Ordner. Die Liste der Profile (Name, Emoji, `admin`, PIN als PBKDF2-Hash) steht in der Einstellung `profiles` der Hauptdatenbank.

- `Handler.route` bestimmt vor jedem Endpunkt das Profil: aus dem Cookie `sunak_profile=<id>.<hmac>` (HMAC aus dem Geheimnis der Installation, der Id und dem PIN-Hash; eine geänderte PIN meldet daher andere Geräte aus dem Profil ab) oder, wenn es nur ein Profil ohne PIN gibt, dieses. Sonst antworten alle Endpunkte außer Profilwahl, Login und Status mit 409 „Choose a profile“, die Seite zeigt dann die Auswahl.
- `App.view(id)` liefert eine `ProfileView`: dieselbe `App`, aber mit `db` und `user_dir` des Profils. Alles andere (Provider, MCP-Manager, Agent-Läufe, Handy-Zugriff) leitet sie an die `App` weiter. Die Endpunkte merken davon nichts, sie benutzen wie bisher `self.app.db`.
- Einstellungen: `GLOBAL_PREFS` (Update-Prüfung, Agent, Spracheingabe) sowie `providers`, `mcp_servers` und das Passwort gelten für die Installation und liegen in der Hauptdatenbank; Theme, Sprache, Systemprompt, Personas, Mail-Konten und Kalender je Profil.
- Admin-Rechte: `ADMIN_ONLY` listet die Endpunkte, die nur Admin-Profile aufrufen dürfen (Profile anlegen und löschen, Modelle laden und löschen, Ollama, Updates, Handy-Zugriff, Agent und MCP), `put_settings` weist globale Einstellungen von anderen Profilen mit 403 ab. Die Seite blendet diese Bereiche für sie aus (`body.not-admin .admin-only`).
- Grenzen: Die PIN trennt die Profile in der App. Wer am Computer angemeldet ist, kann die Dateien aller Profile lesen; ein Admin-Profil mit Agent-Modus oder MCP-Werkzeugen ebenfalls. Das Passwort (Login) gilt für die ganze Installation.

## Modellsuche

Die Modelle-Seite filtert Sunaks Kataloge (Ollama-Modelle mit Tags `chat`, `vision`, `coding`, `reasoning`; Bildmodelle) sofort im Browser nach Text, Typ, Größe und „passt zu meinem Computer“. „Search online“ ruft `/api/models/search` auf: `modelsearch.ollama_search` liest die Suchseite von ollama.com (es gibt keine offizielle Such-API; der Parser ist tolerant und liefert im Zweifel nichts), `hf_search` fragt `GET /api/models?search=…&filter=gguf` bzw. `pipeline_tag=text-to-image` bei Hugging Face. Beide laufen parallel mit kurzem Timeout; was nicht antwortet, fehlt einfach. `hf_files` liest Modellinfo (Lizenz, `gated`) und Dateiliste (`/tree/main`); GGUF-Dateien lädt Ollama direkt als `hf.co/<repo>:<quant>`, Bild-Checkpoints lädt `sdcpp`.

## Bildgenerierung

Zwei Wege: Sunaks eigenes Bildprogramm (`sdcpp.py`, `image_gen = local`) oder ein Stable-Diffusion-Programm, das der Nutzer selbst betreibt (`imagegen.py`). Einstellungen (nur Admin-Profile): `image_gen` (`off`, `local`, `automatic1111`, `comfyui`), `image_gen_url` (leer = `DEFAULT_URLS`), `image_gen_model`, `image_gen_size` (512, 768 oder 1024 als Seite eines quadratischen Bildes; Hoch- und Querformat 2:3 bzw. 3:2 mit etwa gleicher Fläche, Vielfache von 64) und `image_gen_steps`.

- **Eigenes Programm (stable-diffusion.cpp):** `GET /repos/leejet/stable-diffusion.cpp/releases/latest` listet die fertigen Programme; `rank_assets` wählt nach System, Prozessor und Grafikkarte (NVIDIA: CUDA mit der CUDA-Laufzeit als zweitem Archiv, andere Karten: Vulkan, Mac: Metal, sonst die AVX2-Version). Der Nutzer sieht die Liste und klickt; der Server nimmt nur Namen aus dieser Liste an. Das ZIP wird geprüft (keine Pfade außerhalb), nach `<data>/imagegen/engine` entpackt, das Programm (`sd-cli` oder `sd`) gesucht und in `engine.json` gemerkt. Modelle kommen aus `CATALOG` (Hugging-Face-Repository, Datei, Rolle, Lizenz, empfohlene Größe, Schritte, CFG, Sampler) oder aus der Suche (eine Checkpoint-Datei, `model.json` im Modellordner) nach `<data>/imagegen/models/<id>/`. `download` schreibt in eine `.part`-Datei und setzt mit `Range` fort; Abbrechen ist eine Pause. Für ein Bild startet `generate` das Programm mit `-m/--vae`, `-p`, `-n`, `-W`, `-H`, `--steps`, `--cfg-scale`, `--sampling-method`, `-s`, `-o`, liest den Fortschrittsbalken (`3/20`) für die Anzeige und beendet den Prozess bei Stop. Bildgröße, Schritte und CFG kommen vom Modell.
- **Was fehlt:** `sdcpp.status` prüft Programm, gewähltes und heruntergeladene Modelle und liefert `{problem, model}`: `no_engine`, `no_model`, `choose` (alles da, aber `image_gen` noch `off` oder Modell fehlt: `model` ist das zu nehmende) oder leer. `GET /api/settings` enthält das als `image_status`. Es gibt keinen Bild-Knopf: Ist etwas nicht eingerichtet, nennt `imagineSetup` bei einem Bildwunsch im Chat den fehlenden Schritt (bei `choose` richtet es alles selbst ein). Nach Programm-Installation, Modell-Download und Löschen holt `refreshImageStatus` die Einstellungen neu. **Bitte im normalen Chat:** Vor dem Senden (nicht mit Anhängen, nicht im Agent-Modus, höchstens 600 Zeichen) fragt `pictureIntent` `POST /api/imagine/intent`; `sunak/intent.py` erkennt Deutsch und Englisch mit Mustern (`classify`). Sind Bilder eingerichtet und `ai_image_detect` an (Standard, globale Einstellung), entscheidet bei `yes` die Regel allein (kein Zusatzaufruf); bei `maybe` und `no` fragt der Server das Chatmodell (`App.ask_intent`: nur die letzte Nachricht, Ja/Nein, Temperatur 0, der Strom wird nach den ersten Zeichen geschlossen), und nur ein JA macht ein Bild (`via: model`). Kein Modell, Fehler, mehr als 15 s oder ein gerade ausgelastetes Backend (`jobqueue.snapshot`, so entsteht keine Wartezeit und kein doppelter Platz) heißt: die Regeln entscheiden (`via: rules`, nur `yes` zählt, `maybe` ist normaler Chat). Ohne eingerichtete Bilder gibt es keinen Zusatzaufruf. Läuft der Server nicht rechtzeitig, bricht der Browser nach 30 s ab und die Nachricht geht als Chat. `pictureRequest` schickt es ohne Rückfrage an `/api/imagine` mit `improve: true`, dem Chatmodell des Chats, `aspect: auto` und der schlichten Beschreibung (`subject` der Intent-Antwort) als `fallback`. Das Chatmodell schreibt den Prompt (`IMPROVE_SYSTEM`: ein englischer Satz aus Stichwörtern, 25 bis 50 Wörter, nichts Unerbetenes dazuerfinden); der Nutzer sieht ihn schon beim Malen (`prompt`-Ereignis) und danach als „Improved prompt" unter dem Bild (`meta.imagegen.prompt`, die Bitte steht in `meta.imagegen.request`; die Nutzernachricht bleibt im Wortlaut). Kein Werkzeugaufruf des Modells, damit es mit jedem Modell geht. Ist nichts eingerichtet, nennt ein Hinweis den fehlenden Schritt (bei `choose` richtet `imagineSetup` alles selbst ein) und die Nachricht geht als normaler Chat an das Modell. Im Agent-Modus wird nichts automatisch gemalt: `pictureIntent` fragt dort nur mit den Regeln (`quick`), und ein Hinweis sagt, dass der Agent die Bitte bekommt. Jede erkannte (oder vom Chatmodell abgelehnte) Bitte steht als INFO „Picture request check“ im Log. Fehler des Programms (`generate`) nennen Exit-Code und die letzten Fehlerzeilen.
- **Automatic1111** (auch Forge, SD.Next; Start mit `--api`): `POST /sdapi/v1/txt2img` in einem eigenen Thread, währenddessen `GET /sdapi/v1/progress` für den Balken; ein gewähltes Modell geht als `override_settings.sd_model_checkpoint` mit. Abbruch: `POST /sdapi/v1/interrupt`.
- **ComfyUI:** der Standard-Workflow (Checkpoint laden, zwei Text-Encoder, leeres Latent, KSampler mit euler/normal, VAE-Decode, SaveImage) im API-Format an `POST /prompt`, dann `GET /history/<id>` bis zum Ergebnis und das Bild über `GET /view`. Ohne gewähltes Modell nimmt Sunak den ersten Checkpoint aus `/object_info/CheckpointLoaderSimple`. Abbruch: Auftrag aus der Warteschlange löschen und `POST /interrupt`.
- Der Seed wird immer von Sunak gewählt (oder mitgegeben), damit er beim Bild steht. Das Bild wird wie ein angehängtes in `images/` gespeichert (`images.store`, Dateisignatur geprüft); die Antwortnachricht hat `meta.images` und `meta.imagegen` (Programm, Modell, Seed, Größe, Schritte, Beschreibung) und als Text eine kurze Beschreibung, damit Folgefragen im Chat Sinn ergeben. Erzeugte Bilder werden dem Modell nicht als Bild geschickt (`images.attach` nimmt nur Bilder von Nutzernachrichten).
- Bricht der Browser ab (Stop), schlägt das nächste `progress`-Event fehl; `generate` merkt das über `cancelled()` und bricht im Programm ab.

## Handy-Zugriff

`App.start_lan` öffnet einen zweiten `ThreadingHTTPServer` mit derselben `App` auf der Netzwerkadresse des Computers und demselben Port (eine andere Adresse auf demselben Port lässt sich auf allen drei Systemen binden). Die Adresse liefert `lan_ip`: ein UDP-`connect` ohne gesendetes Paket zeigt, über welche Adresse der Computer nach außen spricht. Der Haupt-Server bleibt auf `127.0.0.1`.

- Einschalten geht nur mit Passwort; wird das Passwort entfernt, schließt `save_settings` den Zugang sofort. Anfragen über die Netzwerkadresse gelten nicht als lokal (Agent-Modus und Beenden brauchen dort ein Login).
- Der Zustand steht in der Einstellung `lan_access`; `__main__` ruft beim Start `restore_lan` auf und gibt die Adresse aus. Klappt das nicht (kein Netzwerk), steht der Grund in `lan_info()["error"]`.
- Mit `--host 0.0.0.0` ist Sunak ohnehin im Netz erreichbar (`fixed`), dann zeigt die Seite nur Adresse und Code.
- `GET /api/lan` liefert Zustand, Adresse und den QR-Code als SVG, `POST /api/lan {enabled}` schaltet um.
- `sunak/qr.py` erzeugt QR-Codes ohne Abhängigkeiten (Byte-Modus, Fehlerkorrektur M, Versionen 1 bis 10, Maskenwahl nach Strafpunkten). Die Tests vergleichen die Matrizen mit der Bibliothek `qrcode`.
- Die Seite hat ein Web-App-Manifest und die Meta-Tags für „Zum Startbildschirm hinzufügen“. Über `http://` im WLAN behandeln Android und iOS Sunak dabei wie ein Lesezeichen mit eigenem Icon; eine vollwertige PWA-Installation verlangen die Browser nur über HTTPS oder localhost.

## Frontend

`app.js` ist eine einzige Datei ohne Framework und gliedert sich in Abschnitte: API-Helfer, Markdown-Renderer, Theme, Navigation, Modelle, Chats, Senden, Modell-Download, Compare, Research, Dokumente, Notizen, Einstellungen und Start.

- Der Markdown-Renderer maskiert zuerst alles HTML und baut dann nur bekannte Elemente auf. Modellausgaben können daher kein Skript einschleusen.
- Streams werden mit `fetch` und einem `ReadableStream` zeilenweise gelesen und pro Animationsframe neu gezeichnet.
- **Themes:** Jedes Theme ist ein Block `[data-theme="…"]` in `app.css`, der alle Farben als CSS-Variablen setzt (`--bg`, `--panel`, `--panel-2`, `--border`, `--text`, `--muted`, `--code-bg`, `--danger`, `--ok`, `--accent`, `--accent-text`), dazu bei Bedarf Schrift (`--font`), Ecken (`--radius`) und Leuchten (`--glow`). Mitgeliefert: `dark`, `light`, `retro`, `cyberpunk`, `ocean`, `forest`, `sunset`, `corporate`. Themes mit eigener Form (Retro, Cyberpunk, 80s Corporate) haben zusätzlich ein paar Regeln `[data-theme="…"] .klasse` am Ende von `app.css`, etwa die 3D-Ränder (`--bevel-hi`, `--bevel-lo`) und die Titelleiste von 80s Corporate. Die Liste steht dreimal und muss übereinstimmen: CSS, `THEMES` in `app.js` (Name, Untertitel) und `THEMES` in `server.py` (erlaubte Werte); `tests/test_themes.py` prüft das und den Kontrast (Text mindestens 7:1, gedämpfter Text, Akzent, Fehler- und Erfolgsfarbe mindestens 4,5:1, Schrift auf Akzent-Knöpfen mindestens 4,5:1).
- **Neues Theme:** Block in `app.css` kopieren und Farben ändern, Eintrag in beiden `THEMES`-Listen ergänzen, Tests laufen lassen.
- **Auswahl:** Der Paletten-Knopf in der oberen Leiste (Menü) und Karten mit Vorschau in Settings → Look. Die Karten tragen selbst `data-theme`, zeigen also das echte Theme. Ein Klick gilt sofort und wird gleich gespeichert (`PUT /api/settings` mit `theme` und `accent`).
- **Akzentfarbe:** `accent` leer heißt „Farbe des Themes“. Eine eigene Farbe wird als Inline-Variable auf `<html>` gesetzt; die Schriftfarbe darauf (schwarz oder weiß) berechnet `theme.js` aus der Helligkeit.
- **Ohne Flackern:** `static/theme.js` wird im `<head>` von `index.html` und `login.html` geladen, bevor die Seite gezeichnet wird, und setzt Theme und Akzent aus `localStorage`. `app.js` schreibt die Werte aus den Einstellungen dorthin zurück, damit jedes Gerät die zuletzt gewählten Werte sofort hat.

## Icons

Die Oberfläche nutzt keine Emojis, sondern eigene Strich-Icons (`static/icons.js`, 24×24, `stroke: currentColor`), damit sie in jedem Theme die Textfarbe haben und überall gleich aussehen. `SUNAK_ICONS` bildet den Namen auf den SVG-Inhalt ab. In `index.html` steht `<i data-i="mail"></i>`, das `icons.js` beim Laden durch ein `<svg class="ic">` ersetzt; in `app.js` liefert `icon('mail')` das Element. Icons sind Dekoration (`aria-hidden`): den Namen eines Knopfes tragen sein Text, `title` oder `aria-label`. Klassen: `solo` (Knopf nur mit Icon), `after`/`before` (Abstand zum Text). Ein neues Icon ist ein Eintrag in `SUNAK_ICONS`. `tests/test_icons.py` prüft, dass jedes benutzte Icon existiert und in Seite und Code keine Emojis mehr stehen. Nur Nutzerinhalte (Mails, Chats) und ein selbst gewähltes Profil-Emoji dürfen Emojis enthalten.

## Spracheingabe und Vorlesen

- **Mikrofon mit Whisper (ganz lokal):** Ist unter Einstellungen → Voice ein Whisper-Server eingetragen, nimmt der Browser mit `MediaRecorder` auf, bis man das Mikrofon noch einmal klickt. `toWav` in `app.js` dekodiert die Aufnahme (WebM, Ogg oder MP4, je nach Browser), rechnet sie mit einem `OfflineAudioContext` auf 16 kHz mono um und schickt sie als WAV an `POST /api/transcribe`. `speech.py` reicht sie als `multipart/form-data` weiter: an whisper.cpp (`…/inference`) oder an einen OpenAI-kompatiblen Server (`…/v1/audio/transcriptions`, z. B. Speaches, faster-whisper-server, LocalAI; Modellname aus `whisper_model`, sonst `whisper-1`). WAV liest jeder dieser Server ohne ffmpeg. Der Text landet im Eingabefeld, gesendet wird erst auf Klick.
- **Mikrofon ohne Whisper:** die Spracherkennung des Browsers (`SpeechRecognition`). Mit `speech_input: "local"` (Standard) nur auf dem Gerät: Google Chrome ab 139 kann dafür ein Sprachmodell laden (`SpeechRecognition.available/install` mit `processLocally`); andere Browser bieten das nicht, dann erklärt ein Hinweis die Einrichtung. Mit `"browser"` darf der Browser seine normale Erkennung nutzen; Chrome schickt den Ton dabei an Google, das steht so in den Einstellungen. `"off"` blendet das Mikrofon aus.
- **Mikrofon nur sicher:** Browser geben das Mikrofon nur auf `localhost` oder über HTTPS frei. Über den Handy-Zugriff (`http://` im WLAN) geht das Mikrofon deshalb nicht; dort hilft die Diktierfunktion der Handy-Tastatur.
- **Vorlesen:** `speechSynthesis` des Browsers. `speakable` entfernt Denkprozess, Codeblöcke, Markdown, Links und Quellennummern und teilt den Text in Stücke unter 200 Zeichen (lange Texte bricht Chrome sonst ab). Die Stimme wird pro Gerät gewählt (`localStorage`, weil jedes Gerät andere Stimmen hat); „Automatisch“ nimmt eine Stimme, die auf dem Gerät läuft (`localService`), in der Sprache der Oberfläche. Online-Stimmen sind in der Liste markiert.

## Sprachen

Der Quelltext ist englisch. Jede weitere Sprache ist eine Datei `static/lang-<code>.js`, die die englischen Texte auf ihre Übersetzung abbildet (`SUNAK_LANGS.de = { name: 'Deutsch', strings: {…} }`); `{name}` markiert einen wechselnden Teil.

- **Übersetzen beim Erscheinen:** `static/i18n.js` wird im `<head>` nach den Sprachdateien geladen und beobachtet die Seite mit einem `MutationObserver`. Jeder neue Text und die Attribute `title`, `placeholder` und `aria-label` werden nachgeschlagen, also auch alles, was `app.js` später zeichnet, Meldungen (`toast`) und die Browser-Dialoge `confirm`/`prompt`/`alert`. `app.js` bleibt dadurch fast unverändert englisch.
- **Nutzerinhalte nie:** Chats, Antworten (`.md`), E-Mails, Dateinamen, Chat- und Dokumenttitel, Modellnamen und Eingabefelder stehen in `SUNAK_SKIP_TEXT` und werden nie übersetzt, auch wenn sie zufällig einem Oberflächentext gleichen.
- **Zusammengesetzte Texte** (mit Namen, Zahlen, Mehrzahl) übersetzt `app.js` ausdrücklich mit `tr('Delete “{title}”?', { title })` bzw. `trn(n, '{n} file', '{n} files')`. Schlüssel mit Platzhaltern und mindestens zehn festen Zeichen passen außerdem auf fertige Texte; so werden auch Meldungen des Servers übersetzt („Searching the web: …“). Allgemeinere Schlüssel wie `Remove {name}` gelten nur für `tr()`, damit sie keine fremden Texte treffen. Meldungen des Servers, die die Sprachdatei nicht kennt, bleiben englisch.
- **Einstellung:** `language` in den Einstellungen (`""` = Sprache des Browsers, sonst ein Wert aus `LANGUAGES` in `server.py`). Der Browser hält eine Kopie in `localStorage` (`sunak-lang`), damit die Seite sofort in der Sprache startet, auch die Login-Seite; weicht sie von der Einstellung ab (anderes Gerät), lädt die Seite einmal neu. Ein Sprachwechsel lädt die Seite neu.
- **Neue Sprache:** `lang-de.js` kopieren, Texte übersetzen, die Datei in `index.html` und `login.html` vor `i18n.js` einbinden und den Code in `LANGUAGES` ergänzen. `tests/test_i18n.py` prüft, dass alle Texte der Seiten und alle `tr()`-Aufrufe übersetzt sind, die Platzhalter übereinstimmen und keine Übersetzung selbst wieder wie ein englischer Text aussieht.

## Konfiguration

Installer-Optionen: `install.sh --yes --no-ollama --no-start --no-shortcut --autostart`; unter Windows entsprechend die Umgebungsvariablen `SUNAK_YES`, `SUNAK_NO_OLLAMA`, `SUNAK_NO_START`, `SUNAK_NO_SHORTCUT`, `SUNAK_AUTOSTART`, jeweils auf `1` gesetzt. Beide kennen außerdem `SUNAK_HOME` (Ordner des Installers), `SUNAK_REPO` und `SUNAK_BRANCH` (Quelle des Updates).

Umgebungsvariablen von Sunak selbst: `SUNAK_HOST`, `SUNAK_PORT`, `SUNAK_DATA`, `SUNAK_PASSWORD`, `SUNAK_NO_BROWSER`, `SUNAK_DEBUG` (Log-Stufe DEBUG), `SUNAK_REPORT_REPO` (Repository für Fehlerberichte, Standard `M4XM77R/Sunak`), `SUNAK_ALLOWED_HOSTS` (weitere erlaubte Hostnamen, kommagetrennt, `*` für alle; Schutz gegen DNS-Rebinding in `Handler.host_allowed`), `SUNAK_MODEL_SLOTS` (gleichzeitige Anfragen an ein lokales Modell, Standard 1; siehe Warteschlange), `SUNAK_GPU` (nur Docker, `nvidia` oder `amd`), `OLLAMA_BASE_URL`, `ANTHROPIC_API_KEY`, `SEARXNG_URL`, `NO_COLOR`. Docker Compose liest zusätzlich `APP_BIND` (Standard `127.0.0.1`) und `APP_PORT` (Standard `7000`). Alles Weitere wird in der Oberfläche eingestellt und in der Datenbank gespeichert.

## Tests

```bash
python3 -m unittest discover tests -v
```

Die Tests starten Sunak und simulierte Server, die die Ollama-, Anthropic- und OpenAI-API (sowie IMAP, SMTP, CalDAV, MCP, Whisper, Automatic1111, ComfyUI und GitHub) nachbilden; nichts geht ins echte Netz. Installer lassen sich nur statisch prüfen. GitHub Actions führt alles auf Linux, macOS und Windows aus (`.github/workflows/test.yml`).

| Datei | Prüft |
|---|---|
| `test_server.py` | Ende-zu-Ende: Chat, Streaming, Denkprozess, Neu generieren, Gedächtnis-Notizen, Compare, Research, Dokumente, Modell-Download, Ollama-Status und Katalog, Claude (Streaming, Header, Ablehnung, Key-Maskierung), Chat-Suche und Export, Wissensbasis, Datenbank-Migration, Login, CSRF-Schutz, Pfad-Traversal |
| `test_robustness.py` | Feindliche PDFs, falsche Datentypen in Anfragen, Login nach Neustart mit `SUNAK_PASSWORD`, API-Keys bei Weiterleitung auf andere Hosts, Beenden über Reverse-Proxy |
| `test_extract.py` | Textauslese aus PDF, Word, OpenDocument, PowerPoint und die Wissensbasis (Testdateien entstehen im Test) |
| `test_agent.py` | Agent-Modus: Ordnergrenze (`..`, absolute Pfade, Symlinks, verbotene Ordner), Werkzeuge, Befehle mit Zeit- und Ausgabelimit, Tool-Calling je Backend, Textprotokoll, Freigaben, Stop |
| `test_mcp.py` | MCP: simulierter stdio- und HTTP-Server, Werkzeuglisten, Aufrufe, Geheimnisse, Absturz und Neustart, Freigaben im Chat |
| `test_mail.py` | E-Mail gegen simulierten IMAP- und SMTP-Server (auch ohne `MOVE`/`UIDPLUS`), Anhänge, Verschieben, Löschen, neue Mail, Selbsttest |
| `test_calendar.py` | iCalendar, Wiederholungen über die Sommerzeit, Zeitzonen, Schreiben, simulierter CalDAV-Server, ICS-Abos, Termin aus Text |
| `test_memory.py` | Automatisches Gedächtnis: Fakten, Geheimnisse und Duplikate, ausdrückliches „merk dir“ |
| `test_profiles.py` | Profile: Auswahl mit PIN, getrennte Daten, eigene Einstellungen, Admin-Rechte |
| `test_vision.py` | Bilder im Chat: Prüfungen, Ablage, Format je Backend, Modelle ohne Bildverständnis |
| `test_websearch.py` | Web-Suche im Chat: Schalter, Quellen, umformulierte Folgefrage, Fehlerfälle |
| `test_log.py` | Logging: Format, Stufen, Rotation und Größenlimit der Datei, Dateirechte, Maskierung von Geheimnissen, keine Inhalte in den Anfrage-Zeilen, `sunak logs` |
| `test_reports.py` | Fehlerberichte: Anonymisierung, Inhalt ohne Variablenwerte, Fingerabdruck, Modi (aus, fragen, automatisch), Senden gegen ein Fake-GitHub (neues Issue, Kommentar, geschlossenes Issue, Rate-Limit), Token wird nie ausgegeben |
| `test_intent.py` | Erkennung von Bildwünschen: eindeutig/unklar/kein Bildwunsch (Deutsch und Englisch), Beschreibung ohne Bitte, Antwort des Chatmodells, Endpunkt mit Regeln, Chatmodell und nicht eingerichteten Bildern |
| `test_queue.py` | Warteschlange (Reihenfolge, Plätze, mehrere Plätze, Abbruch, Zeitlimit), Wartezeit im Chat bis zum Platz, automatischer Bildwunsch mit Prompt-Verbesserung |
| `test_imagegen.py`, `test_sdcpp.py` | Bildgenerierung (Automatic1111, ComfyUI, eigenes Bildprogramm) und Modellsuche gegen simulierte Server |
| `test_speech.py` | Spracheingabe an einen simulierten Whisper-Server beider Arten |
| `test_gpu.py` | GPU-Erkennung mit simulierter Ausgabe, sysfs-Bäumen, Registry, Warnung, Empfehlung |
| `test_lan.py` | Handy-Zugriff (nur mit Passwort, zweiter Server, QR-Matrizen) |
| `test_themes.py`, `test_i18n.py`, `test_icons.py` | Oberfläche: Themes (gleiche Namen, Kontrast), Sprachen (alle Texte übersetzt), Icons ohne Emojis |
| `test_cli.py`, `test_desktop.py` | Hilfe und Tippfehler-Hinweise, `status`, `stop`, Autostart-Dateien |
| `test_updates.py` | Update-Prüfung und Update-Knopf mit echten Git-Repositories |
| `test_installers.py`, `test_uninstall.py` | Installer (statisch) und `sunak uninstall` |

## Erweitern

- **Neuer API-Endpunkt:** Methode auf `Handler` schreiben und in `ROUTES` eintragen; Ausnahmen vom Typ `ValueError` werden automatisch als 400 beantwortet.
- **Neues Modell im Katalog:** Eintrag in `CATALOG` in `sunak/ollama.py` ergänzen (Ollama-Name, Titel, Größe in GB, Tags, Beschreibung).
- **Neuer Backend-Typ:** `list_models` und `chat_stream` in `providers.py` um den Typ erweitern und den Typ in `App.save_settings` zulassen.
- **Neue Ansicht:** einen `<section class="view" id="view-…">` und einen Navigationsknopf in `index.html` anlegen, die Logik als eigenen Abschnitt in `app.js` ergänzen und in `show()` einhängen.


## Warteschlange für Modellanfragen

Mehrere Nutzer (Profile, Handy, andere Geräte) teilen sich dieselben Backends, also stehen Anfragen in einer Reihe, **first in, first out** (`sunak/jobqueue.py`).

- **Eine Reihe je Backend:** `chat:<Anbieter-Id>` für jeden Chatmodell-Anbieter (`providers.queue_key`), `image` für den Bildgenerator. Lokale Backends (`providers._is_local`) haben `SUNAK_MODEL_SLOTS` Plätze (Standard 1: eine schwere Anfrage auf einmal), Backends im Internet vier.
- **Wo der Platz gehalten wird:** `providers.chat_stream` (und damit `chat_once`: Suchanfrage, Gedächtnis, Prompt-Verbesserung, Mail- und Kalenderhilfe), in `agent.Run._turn` um jeden einzelnen Modellaufruf (die drei Tool-Protokolle rufen `providers._request` selbst auf) und in `/api/imagine` um die Bilderzeugung. Der Platz wird nie gehalten, während der Agent auf die Bestätigung des Nutzers wartet. Die Prompt-Verbesserung und das Malen sind zwei getrennte Plätze in zwei Reihen und halten nie beide zugleich.
- **Anzeige:** `start_stream` hängt dem Anfrage-Thread ein `notify` an (`jobqueue.local`), das `{"type": "queued", "position": n}` in den NDJSON-Strom schreibt (nur wenn gewartet wird; zuletzt `position: 0`). Der Browser zeigt „Waiting in the queue: place n" im Chat-Status, als Hinweis im Agent-Verlauf und im Bild-Platzhalter. Ereignisse gehen mindestens alle zwei Sekunden hinaus; schlägt das Schreiben fehl (Stop, Tab zu), verlässt die Anfrage die Reihe, ohne je ans Modell zu gehen. Anfragen ohne Strom (zum Beispiel `/api/calendar/parse`) warten still.
- **Grenzen:** Wartet eine Anfrage länger als 15 Minuten, bekommt der Nutzer eine Fehlermeldung. Die Reihe liegt im Arbeitsspeicher und gilt je Sunak-Prozess; Anfragen, die nicht über Sunak laufen (Ollama von Hand), sieht sie nicht. Bildgenerator und Chatmodell auf derselben Grafikkarte sind zwei getrennte Reihen; stehen beide unter Last, teilen sie sich die Karte.


## Fehlerberichte

Die Berichte landen in einem öffentlichen Repository (Warnung in den Einstellungen, Rückfrage beim Einschalten von „auto“, Hinweis am Bericht und im Issue). Details zu Inhalt, Anonymisierung und Doppelten stehen bei `sunak/reports.py` (Tabelle Dateien) und im README (Fehlerberichte). Ablauf: Ein Fehler, der mit Traceback geloggt wird (`log_http.error` bei HTTP 500, `log_app.error` bei unerwarteten Fehlern, abgestürzte Threads), geht an `Reports.capture`. Bei `off` passiert nichts. Sonst entsteht ein Bericht in `reports.json` (höchstens 20 wartende; derselbe Fehler zählt hoch). Bei `auto` mit Token sendet ein Hintergrund-Thread ihn sofort, sonst entscheidet der Nutzer in Settings → Error reports. Beim Senden gilt: erst das Rate-Limit, dann Suche nach dem Fingerabdruck in den Issue-Titeln, dann Kommentar oder neues Issue. Ein Fehler beim Senden (kein Netz, Token abgelehnt) lässt den Bericht warten; die Fehlermeldung des Servers (`ReportError`, eine `ValueError`, also HTTP 400) erscheint als Hinweis. Das Senden selbst loggt nur WARNING, damit es keine Berichtsschleife gibt (`_local.busy` schützt zusätzlich).

## Logging

Alles läuft über `sunak/log.py`; kein `print` für Betriebsmeldungen (die Startanzeige in `__main__` bleibt).

- **Wohin:** Terminal (stderr) und `<Datenordner>/logs/sunak.log`. Die Datei rotiert bei 10 MB (`MAX_BYTES`) und behält vier Sicherungen (`BACKUPS`), zusammen also höchstens 50 MB; `os.chmod 600`. Lässt sich der Ordner nicht anlegen, loggt Sunak nur ins Terminal und sagt das einmal. Terminal-Zeile: `HH:MM:SS STUFE Bereich Text`, Datei-Zeile mit Datum.
- **Stufen:** INFO im Normalbetrieb, DEBUG mit `SUNAK_DEBUG`. Anfragen (`Handler.route`): ändernde API-Aufrufe INFO, lesende und statische DEBUG, 4xx WARNING (außer 401/404 auf Lese- und Seitenanfragen: DEBUG), 5xx ERROR; bei Strömen steht ein Fehlerereignis in der Zeile (`stream error: …`, auf 200 Zeichen gekürzt). Ungefangene Fehler mit Stacktrace (`exc_info`). Warteschlange: wartet („busy, … place n“), dran („its turn after …“), verlassen, Zeitlimit. Bilder: Auftrag (Programm, Format), Prompt-Verbesserung (Modell, Dauer, Ausweichen), Ergebnis (Dauer, Größe, Schritte) oder Fehler. Außerdem Start und Ende, Update-Prüfungen und -Installation, Modellfehler (Anbieter und gekürzte Meldung).
- **Was nie hineinkommt:** Inhalte von Chats, Prompts, Antworten, Mails, Dateien; Passwörter, API-Schlüssel, Tokens, Cookies; Query-Strings (nur der Pfad wird protokolliert). Zusätzlich läuft jede Zeile samt Stacktrace durch `redact`. Neue Log-Aufrufe dürfen deshalb nur Metadaten nennen (Modell-Id, Dauer, Anzahl), nie `request`, `prompt` oder Nachrichtentexte.
- **`sunak logs [ZEILEN]`:** `log.tail` liest das Ende der Datei (höchstens 256 KB) und gibt Pfad und Zeilen aus.
