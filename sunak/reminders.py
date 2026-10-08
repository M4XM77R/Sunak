"""Calendar reminders. Events carry reminders (iCalendar VALARM, see cal.alarms). While Sunak runs, a background
thread looks at the upcoming events of every profile that turned reminders on and, when one is due, (1) keeps it
for the open pages, which show a message and a browser notification, and (2) sends it as a push message to the
profile's ntfy topic (https://ntfy.sh or a self-hosted server), so it also arrives on the phone while no browser
is open. Real Web Push needs encryption the standard library does not have; ntfy only needs one HTTP request.

Pure standard library."""

import datetime as dt
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import cal, log, providers

log_rem = log.get("reminders")

TICK = 30                         # seconds between two looks at the due reminders
REFRESH = 600                     # seconds an event list is reused (a change in Sunak's own calendar refreshes it at once)
HORIZON = dt.timedelta(days=8)    # how far ahead events are read (the longest reminder is 7 days before)
LATE = 600                        # a reminder at or after the start is still shown this many seconds late
KEEP = 900                        # seconds a due reminder waits for a page that is not open yet
DEFAULT_NTFY = "https://ntfy.sh"
TOPIC_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
NTFY_TIMEOUT = 10


class ReminderError(ValueError):
    """The push message could not be sent; the message is for the user."""


# the push message --------------------------------------------------------------------------------

TEXTS = {
    "en": {"now": "Starts now", "in": "Starts in {n}", "min": ("minute", "minutes"), "hour": ("hour", "hours"),
           "day": ("day", "days"), "allday": "All day, {date}", "test_title": "Sunak", "test": "Reminders work. This is a test."},
    "de": {"now": "Beginnt jetzt", "in": "Beginnt in {n}", "min": ("Minute", "Minuten"), "hour": ("Stunde", "Stunden"),
           "day": ("Tag", "Tagen"), "allday": "Ganztägig, {date}", "test_title": "Sunak", "test": "Erinnerungen funktionieren. Das ist ein Test."},
}


def _span(minutes, t):
    for unit, size in (("day", 1440), ("hour", 60)):
        if minutes % size == 0 and minutes >= size:
            n = minutes // size
            return f"{n} {t[unit][n != 1]}"
    return f"{minutes} {t['min'][minutes != 1]}"


def message(ev, lead, start, lang="en"):
    """(title, text) of the reminder for event `ev` (an entry of cal.events_in) `lead` minutes before `start`."""
    t = TEXTS.get(lang) or TEXTS["en"]
    if ev["all_day"]:
        date = start.strftime("%d.%m.%Y" if lang == "de" else "%Y-%m-%d")
        line = t["allday"].format(date=date)
    elif lead > 0:
        line = t["in"].format(n=_span(lead, t)) + f" ({start.astimezone().strftime('%H:%M')})"
    else:
        line = t["now"]
    if ev.get("location"):
        line += " · " + ev["location"]
    return (ev["summary"] or "Event")[:200], line[:500]


# which reminders are due -------------------------------------------------------------------------

def start_of(ev):
    """The start of an event as an aware datetime (all-day events: midnight of this computer's time zone)."""
    if ev["all_day"]:
        return dt.datetime.combine(dt.date.fromisoformat(ev["start"]), dt.time()).astimezone()
    return dt.datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))


def due(events, now):
    """[(key, event, lead, start)] of the reminders that should have gone off by `now` and are not too late:
    from the moment `lead` minutes before the start until the start (a reminder at or after the start: for LATE seconds)."""
    out = []
    for ev in events:
        if ev.get("status") == "cancelled" or not ev.get("alarms"):
            continue
        try:
            start = start_of(ev)
        except ValueError:
            continue
        for lead in ev["alarms"]:
            fire = start - dt.timedelta(minutes=lead)
            if fire <= now < (start if lead > 0 else fire + dt.timedelta(seconds=LATE)):
                out.append((f"{ev['id']}|{lead}", ev, lead, start))
    return out


# ntfy --------------------------------------------------------------------------------------------

def ntfy_server(url):
    return (url or "").strip().rstrip("/") or DEFAULT_NTFY


def send_ntfy(url, topic, title, text):
    """Publish one message to the ntfy topic. Raises ReminderError."""
    base = ntfy_server(url)
    payload = json.dumps({"topic": topic, "title": title, "message": text, "tags": ["calendar"]}).encode()
    req = urllib.request.Request(base, data=payload, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "sunak"})
    opener = cal._DIRECT if providers._is_local(base) else cal._PROXY  # no redirects: nothing is sent to another address
    try:
        with opener.open(req, timeout=NTFY_TIMEOUT) as r:
            r.read(2000)
    except urllib.error.HTTPError as e:
        raise ReminderError(f"The ntfy server answered with HTTP {e.code}. Check the address and the topic.") from None
    except (urllib.error.URLError, OSError) as e:
        raise ReminderError(f"Cannot reach {urllib.parse.urlparse(base).netloc}: {getattr(e, 'reason', e)}") from None


# the background thread ---------------------------------------------------------------------------

class Reminders:
    """Looks for due reminders of all profiles (every TICK seconds) once `start` was called."""
    def __init__(self, app):
        self.app = app
        self._lock = threading.Lock()
        self._cache = {}      # profile -> (read at, events)
        self._pending = {}    # profile -> [item, …] for the open pages
        self._failed = set()  # keys of push messages that failed (logged once)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="reminders")
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(TICK):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - one bad round must not end the thread
                log_rem.warning("Reminder check failed", exc_info=True)

    def invalidate(self, pid):
        """The events of a profile changed: read them again at the next look."""
        with self._lock:
            self._cache.pop(pid, None)

    def items(self, pid, since):
        """The reminders of a profile that went off after `since` (a time stamp)."""
        with self._lock:
            return [i for i in self._pending.get(pid, []) if i["ts"] > since]

    def events(self, view, pid, now):
        with self._lock:
            hit = self._cache.get(pid)
        if hit and time.time() - hit[0] < REFRESH:
            return hit[1]
        events, errors = view.calendar_load(now - dt.timedelta(hours=1), now + HORIZON)
        for e in errors:
            log_rem.debug("Calendar %s not read for reminders: %s", e.get("name") or e.get("source"), e.get("error"))
        with self._lock:
            self._cache[pid] = (time.time(), events)
        return events

    def tick(self, now=None):
        """One look at all profiles."""
        now = now or dt.datetime.now(dt.timezone.utc)
        for p in self.app.profiles():
            try:
                self.profile_tick(p["id"], now)
            except Exception:  # noqa: BLE001 - the other profiles still get their reminders
                log_rem.warning("Reminder check for profile %s failed", p["id"], exc_info=True)

    def profile_tick(self, pid, now):
        view = self.app.view(pid)
        s = view.settings()
        if not s["reminders"]:
            with self._lock:
                self._cache.pop(pid, None)
            return
        topic = s["ntfy_topic"]
        if topic:
            log.add_secret(topic)
        db = view.db
        for key, ev, lead, start in due(self.events(view, pid, now), now):
            title, text = message(ev, lead, start, s["reminder_lang"])
            if not db.reminder_seen(key + "|page"):
                db.reminder_mark(key + "|page")
                item = {"id": key, "ts": time.time(), "title": title, "text": text, "start": ev["start"], "all_day": ev["all_day"]}
                with self._lock:
                    kept = [i for i in self._pending.get(pid, []) if i["ts"] > time.time() - KEEP]
                    self._pending[pid] = kept + [item]
            if topic and not db.reminder_seen(key + "|ntfy"):
                try:
                    send_ntfy(s["ntfy_url"], topic, title, text)
                    db.reminder_mark(key + "|ntfy")
                    self._failed.discard(key)
                except ReminderError as e:  # tried again at the next look while the reminder is due
                    if key not in self._failed:
                        self._failed.add(key)
                        log_rem.warning("Push message for “%s” not sent: %s", title, e)
