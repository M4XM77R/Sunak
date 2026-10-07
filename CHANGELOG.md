# Changelog

Alle Änderungen an Sunak, neueste Version zuerst. Sunak zeigt die Einträge zwischen deiner und der neuen Version an, **bevor** du ein Update installierst: in der App (Update-Knopf, Settings → Updates) und im Terminal (`sunak update`, `sunak changelog`).

Format: ein Abschnitt je Version als `## [a.b.c] – JJJJ-MM-TT`, darunter kurze Punkte unter **Neu**, **Geändert**, **Behoben** oder **Entfernt**. Jede Änderung an Sunak bekommt eine neue Version und einen Eintrag hier.

## [0.14.0] – 2026-10-07

### Neu
- Changelog: Vor dem Update zeigt Sunak, was sich ändert. In der App öffnet der Update-Knopf zuerst eine Liste der Änderungen (Installieren oder Abbrechen), und Settings → Updates zeigt sie unter „Check for updates now“.
- `sunak update` zeigt die Änderungen und fragt „Install the update now? [y/N]“. Mit `--yes` (oder `-y`) und ohne Terminal (Skripte, Autostart, Update-Knopf) wird nicht gefragt.
- `sunak changelog` zeigt die Änderungen des nächsten Updates, ohne etwas zu installieren; ist Sunak aktuell, die der installierten Version.
- Fehlt die Datei `CHANGELOG.md` oder ist sie kaputt, geht das Update trotzdem, mit dem Hinweis „No changelog available“.

## [0.12.3] – 2026-10-07

### Behoben
- Der Geschwindigkeitstest des Token-Zählers hängt nicht mehr von der Uhr des Testrechners ab (schlug unter Windows fehl).

## [0.12.2] – 2026-10-07

### Behoben
- Token-Zähler: Gestoppte Claude-Antworten erzeugen keine Platzhalter-Ausgabe mehr, eine Null in `message_delta` überschreibt keine echten Zahlen, `stream_options` wird nur wiederholt, wenn der Server sie nennt, und die Ausgabezeit von Werkzeugaufrufen wird mitgezählt.

## [0.12.1] – 2026-10-07

### Entfernt
- Token-Zähler: der Fortschrittsbalken bis 1.000.000.000 Tokens.

## [0.12.0] – 2026-10-07

### Neu
- Token-Zähler je Profil: für alle Anbieter und den Agent, mit Tokens pro Sekunde und der Gesamtsumme.

## [0.11.1] – 2026-10-07

### Behoben
- Der Recherche-Test erreicht nicht mehr die echte Websuche (hing in der macOS- und Windows-CI).

## [0.11.0] – 2026-10-07

### Neu
- Bildwünsche werden auch in der Tiefenrecherche erkannt; jede Prüfung steht im Log.
- Websuche: Suchanfragen von Modellen (Qwen) werden bereinigt, DuckDuckGo Lite und Bing dienen als Ausweichen, und Sunak sagt, warum eine Suche scheiterte.

## [0.10.1] – 2026-10-07

### Geändert
- Fehlerberichte wissen, dass das Repository öffentlich ist: strenges Schwärzen, Warnungen und Rückfrage vor dem automatischen Senden. Die Doku geht nicht mehr von einem privaten Repository aus.

## [0.10.0] – 2026-10-07

### Neu
- Bildwünsche prüft das Chat-Modell (Einstellung, standardmäßig an); eindeutige Wünsche werden ohne Rückfrage gemalt.

## [0.9.4] – 2026-10-07

### Behoben
- Bildwünsche scheitern nie still: Es gibt einen Hinweis, wenn Bilder nicht eingerichtet sind oder der Agent-Modus an ist, und jede Prüfung steht im Log.

## [0.9.3] – 2026-10-07

### Behoben
- Kurze Bildwünsche ohne Verb werden erkannt („a picture of: …“, „Bild von …“, „draw a cat“).

## [0.9.2] – 2026-10-07

### Behoben
- Bildwünsche werden zuverlässiger erkannt (Regeln plus Chat-Modell bei unklaren Nachrichten).

## [0.9.1] – 2026-10-07

### Geändert
- Doku: Wer für Fehlerberichte ein GitHub-Konto braucht.

## [0.9.0] – 2026-10-07

### Neu
- Fehlerberichte als GitHub-Issues: freiwillig, anonymisiert, mit Vorschau, Duplikat-Erkennung und Begrenzung der Anzahl.

## [0.8.1] – 2026-10-07

### Geändert
- Doku: die Versionsregel a.b.c.

## [0.8.0] – 2026-10-07

### Neu
- Besseres Logging im Terminal und in einer Logdatei von höchstens 50 MB (`sunak logs`).

## [0.7.1] – 2026-10-07

### Behoben
- Der Warteschlangen-Test hängt nicht mehr vom Start der Threads ab (schlug in der macOS-CI fehl).

## [0.7.0] – 2026-10-07

### Neu
- Bildwünsche im Chat werden automatisch mit einem verbesserten Prompt gemalt.
- Anfragen an Modelle laufen in einer Warteschlange (der Reihe nach).

## [0.6.2] – 2026-10-07

### Geändert
- Doku mit den Hinweisen zur Update-Prüfung zusammengeführt.

## [0.6.1] – 2026-10-07

### Geändert
- Doku neu geschrieben und gegen den Code geprüft; der Knopf zur Update-Prüfung ist dokumentiert.

## [0.6.0] – 2026-10-07

### Neu
- Settings → Updates: Knopf „Check for updates now“ prüft sofort und nennt den Grund, wenn es nicht ging.

## [0.5.0] – 2026-10-07

### Geändert
- Versionsnummer angepasst (0.4.0 war schon für die Gedächtnis-Funktion vergeben).

## [0.4.0] – 2026-10-07

### Neu
- Sunak merkt sich Fakten aus Chats von selbst (Gedächtnis).
- Chat-Optionen in einem Aufklappmenü, damit das Textfeld auf dem Handy Platz hat.

## [0.3.0] – 2026-10-07

### Neu
- E-Mail, eigene Linien-Icons statt Emojis und Einrichtung der Bildgenerierung; die Versionsregel ist dokumentiert.

## [0.2.0] – 2026-10-06

### Neu
- Wissensbasis (Dokumente mit eigenem PDF-Leser, Volltextsuche), Chat-Suche und -Export, Personas.
- Autostart, Desktop-Icon und `sunak stop`.
- Update-Hinweis mit Update-Knopf, Sunak zieht Updates per `git pull` aus dem Klon.
- Mehrere Profile mit eigenen Daten, optionaler PIN und Admin-Rechten; Themes; Oberfläche auf Deutsch.
- Kalender (CalDAV, ICS), Spracheingabe und Vorlesen, MCP-Werkzeuge, Websuche mit Quellen, Bilder verstehen (Vision), Zugriff vom Handy per QR-Code.
- Bildgenerierung (Automatic1111, ComfyUI und ein eigenes Programm mit Modell-Downloads), GPU-Erkennung.
- `sunak uninstall`, übersichtliches `sunak -h` mit Hilfe je Befehl.
