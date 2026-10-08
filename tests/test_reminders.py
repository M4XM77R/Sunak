"""Calendar reminders: VALARM in iCalendar, which reminders are due, the push message to an ntfy topic (a fake
server), the background check and the endpoints."""

import datetime as dt
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sunak import cal, reminders
from sunak.server import make_server

import test_server

UTC = dt.timezone.utc
WIDE = (dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2027, 1, 1, tzinfo=UTC))


def events(text):
    return cal.events_in(text, *WIDE, "local")


def event(start, lead, all_day=False, **extra):
    s = start.strftime("%Y-%m-%d") if all_day else start.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": f"local|u|{s}", "uid": "u", "summary": "Zahnarzt", "location": "", "start": s, "end": s, "all_day": all_day,
            "status": "", "alarms": [lead], **extra}


class AlarmTest(unittest.TestCase):
    def test_trigger_roundtrip(self):
        for minutes in (0, 5, 15, 60, 90, 1440, 2880, 10080, -540, 900, 2340, -1):
            self.assertEqual(-cal.parse_duration(cal.trigger(minutes)).total_seconds() / 60, minutes, cal.trigger(minutes))
        self.assertEqual(cal.trigger(15), "-PT15M")
        self.assertEqual(cal.trigger(-540), "PT9H")
        self.assertEqual(cal.trigger(0), "PT0S")

    def test_read_alarms(self):
        text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nDTSTART:20261010T100000Z\r\nSUMMARY:x\r\n"
                "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\n"
                "BEGIN:VALARM\r\nACTION:AUDIO\r\nTRIGGER;RELATED=START:-P1D\r\nEND:VALARM\r\n"
                "BEGIN:VALARM\r\nACTION:EMAIL\r\nTRIGGER:-PT1H\r\nEND:VALARM\r\n"            # e-mail reminders are not ours
                "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER;RELATED=END:-PT5M\r\nEND:VALARM\r\n"  # relative to the end: skipped
                "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER;VALUE=DATE-TIME:20261010T090000Z\r\nEND:VALARM\r\n"  # fixed time: skipped
                "END:VEVENT\r\nEND:VCALENDAR\r\n")
        self.assertEqual(events(text)[0]["alarms"], [15, 1440])
        self.assertEqual(events("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:b\r\nDTSTART:20261010\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")[0]["alarms"], [])

    def test_write_and_change(self):
        start = dt.datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
        text = cal.build_event("u@sunak", "Zahnarzt", start, start + dt.timedelta(hours=1), False, reminder=30)
        self.assertIn("TRIGGER:-PT30M", text)
        self.assertEqual(events(text)[0]["alarms"], [30])
        self.assertEqual(events(cal.build_event("v@sunak", "x", start, start, False))[0]["alarms"], [])
        ev = cal.clean_event({"summary": "Zahnarzt", "start": "2026-10-10T10:00:00Z", "end": "2026-10-10T11:00:00Z"})
        self.assertNotIn("reminder", ev)
        self.assertEqual(events(cal.update_event(text, "u@sunak", ev))[0]["alarms"], [30])  # not asked: stays
        ev["reminder"], ev["reminder_was"] = 5, 30
        self.assertEqual(events(cal.update_event(text, "u@sunak", ev))[0]["alarms"], [5])
        ev["reminder"] = None
        self.assertEqual(events(cal.update_event(text, "u@sunak", ev))[0]["alarms"], [])
        ev["reminder"], ev["reminder_was"] = 15, None  # nothing was shown: one is added
        self.assertEqual(events(cal.update_event(text, "u@sunak", ev))[0]["alarms"], [15, 30])
        ev["reminder"] = 30  # already there: not twice
        self.assertEqual(cal.update_event(text, "u@sunak", ev).count("BEGIN:VALARM"), 1)

    def test_change_keeps_the_other_reminders(self):
        start = dt.datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
        text = cal.build_event("u@sunak", "Zahnarzt", start, start + dt.timedelta(hours=1), False, reminder=30)
        extra = ("BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER;RELATED=END:-PT5M\r\nEND:VALARM\r\n"
                 "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER;VALUE=DATE-TIME:20261010T090000Z\r\nEND:VALARM\r\n"
                 "BEGIN:VALARM\r\nACTION:AUDIO\r\nTRIGGER:-P1D\r\nEND:VALARM\r\n"
                 "BEGIN:VALARM\r\nACTION:EMAIL\r\nTRIGGER:-PT1H\r\nEND:VALARM\r\n")
        text = text.replace("END:VEVENT", extra + "END:VEVENT")
        ev = cal.clean_event({"summary": "Zahnarzt", "start": "2026-10-10T10:00:00Z", "end": "2026-10-10T11:00:00Z",
                              "reminder": 5, "reminder_was": 30})
        changed = cal.update_event(text, "u@sunak", ev)
        self.assertEqual(events(changed)[0]["alarms"], [5, 1440])  # 30 became 5, the day before stayed
        for kept in ("TRIGGER;RELATED=END:-PT5M", "TRIGGER;VALUE=DATE-TIME:20261010T090000Z", "ACTION:EMAIL", "TRIGGER:-P1D"):
            self.assertIn(kept, changed)
        self.assertNotIn("TRIGGER:-PT30M", changed)
        gone = cal.update_event(text, "u@sunak", cal.clean_event({"summary": "Zahnarzt", "start": "2026-10-10T10:00:00Z",
                                                                  "end": "2026-10-10T11:00:00Z", "reminder": None, "reminder_was": 30}))
        self.assertEqual(events(gone)[0]["alarms"], [1440])
        self.assertEqual(gone.count("BEGIN:VALARM"), 4)

    def test_clean_event_reminder(self):
        base = {"summary": "x", "start": "2026-10-10T10:00:00Z", "end": "2026-10-10T11:00:00Z"}
        for given, want in ((None, None), ("", None), (0, 0), (15, 15), (15.0, 15), (-540, -540), (10080, 10080)):
            self.assertEqual(cal.clean_event({**base, "reminder": given})["reminder"], want)
        for bad in (True, "15", 1.5, 10081, -1441, [5]):
            with self.assertRaises(ValueError, msg=bad):
                cal.clean_event({**base, "reminder": bad})
        self.assertEqual(cal.clean_event({**base, "reminder": 5, "reminder_was": 30})["reminder_was"], 30)
        self.assertIsNone(cal.clean_event({**base, "reminder": 5})["reminder_was"])
        with self.assertRaises(ValueError):
            cal.clean_event({**base, "reminder": 5, "reminder_was": "30"})


class Berlin(dt.tzinfo):
    """Europe/Berlin for 2026 without a time zone database (not every system has one)."""
    def utcoffset(self, d):
        naive = d.replace(tzinfo=None)
        return dt.timedelta(hours=2 if dt.datetime(2026, 3, 29, 3) <= naive < dt.datetime(2026, 10, 25, 3) else 1)

    def dst(self, d):
        return self.utcoffset(d) - dt.timedelta(hours=1)

    def tzname(self, d):
        return "CEST" if self.dst(d) else "CET"


class DueTest(unittest.TestCase):
    now = dt.datetime(2026, 10, 10, 9, 50, tzinfo=UTC)

    def keys(self, evs, now=None):
        return [k for k, *_ in reminders.due(evs, now or self.now)]

    def test_window(self):
        start = dt.datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
        self.assertEqual(self.keys([event(start, 15)]), ["local|u|2026-10-10T10:00:00Z|15"])  # 10 minutes to go, 15 asked
        self.assertEqual(self.keys([event(start, 5)]), [])                                      # not yet
        self.assertEqual(self.keys([event(start, 15)], start), [])                              # started: too late
        self.assertEqual(self.keys([event(start, 15)], start + dt.timedelta(minutes=1)), [])
        self.assertEqual(self.keys([event(start, 0)], start + dt.timedelta(minutes=1)), ["local|u|2026-10-10T10:00:00Z|0"])
        self.assertEqual(self.keys([event(start, 0)], start + dt.timedelta(seconds=reminders.LATE + 1)), [])
        self.assertEqual(self.keys([event(start, 15, status="cancelled"), event(start, 15, alarms=[])]), [])
        self.assertEqual(self.keys([{**event(start, 15), "start": "broken"}]), [])

    def test_all_day(self):
        midnight = dt.datetime.combine(dt.date(2026, 10, 10), dt.time()).astimezone()
        day = event(midnight, -540, all_day=True)
        self.assertEqual(self.keys([day], midnight + dt.timedelta(hours=8, minutes=59)), [])
        self.assertEqual(len(self.keys([day], midnight + dt.timedelta(hours=9, minutes=1))), 1)
        before = event(midnight, 900, all_day=True)  # the day before at 9:00
        self.assertEqual(len(self.keys([before], midnight - dt.timedelta(hours=14))), 1)
        self.assertEqual(self.keys([before], midnight - dt.timedelta(hours=16)), [])

    def test_all_day_on_clock_change_days(self):
        """Europe/Berlin: the clocks change on 2026-03-29 (23-hour day) and 2026-10-25 (25-hour day). "9:00 on the
        day" and "9:00 the day before" stay 9:00 on the wall clock."""
        berlin = Berlin()
        local = lambda y, m, d, h: dt.datetime(y, m, d, h, tzinfo=berlin)  # noqa: E731
        for day, lead, wall in ((dt.date(2026, 10, 25), -540, local(2026, 10, 25, 9)), (dt.date(2026, 3, 29), -540, local(2026, 3, 29, 9)),
                                (dt.date(2026, 10, 26), 900, local(2026, 10, 25, 9)), (dt.date(2026, 3, 30), 900, local(2026, 3, 29, 9)),
                                (dt.date(2026, 10, 26), 2340, local(2026, 10, 24, 9)), (dt.date(2026, 3, 30), 2340, local(2026, 3, 28, 9))):
            ev = event(dt.datetime.combine(day, dt.time()), lead, all_day=True)
            fire, _ = reminders.moments(ev, lead, berlin)
            self.assertEqual(fire, wall, (day, lead))
            self.assertEqual(len(reminders.due([ev], wall + dt.timedelta(minutes=1), berlin)), 1)
            self.assertEqual(reminders.due([ev], wall - dt.timedelta(minutes=1), berlin), [])

    def test_message(self):
        start = dt.datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
        ev = event(start, 60, location="Praxis")
        en = reminders.message(ev, 60, start, "en")
        de = reminders.message(ev, 90, start, "de")
        self.assertEqual(en[0], "Zahnarzt")
        self.assertTrue(en[1].startswith("Starts in 1 hour (") and en[1].endswith(") · Praxis"), en)
        self.assertTrue(de[1].startswith("Beginnt in 90 Minuten ("), de)
        self.assertEqual(reminders.message(ev, 0, start, "en")[1], "Starts now · Praxis")
        self.assertEqual(reminders.message(ev, 1440, start, "en")[1].split(" (")[0], "Starts in 1 day")
        self.assertEqual(reminders.message(event(start, 5, all_day=True), 5, start, "xx")[1].split(",")[0], "All day")


class FakeNtfy(BaseHTTPRequestHandler):
    posts, mode = [], "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.mode == "ok":
            self.posts.append(json.loads(body))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        elif self.mode == "redirect":
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
        else:
            self.send_response(500)
            self.end_headers()


class NtfyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeNtfy)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        FakeNtfy.posts, FakeNtfy.mode = [], "ok"

    def test_send(self):
        reminders.send_ntfy(self.url + "/", "sunak-abc123", "Zahnärztin Müller", "Beginnt in 15 Minuten ☺")
        self.assertEqual(FakeNtfy.posts, [{"topic": "sunak-abc123", "title": "Zahnärztin Müller",
                                           "message": "Beginnt in 15 Minuten ☺", "tags": ["calendar"]}])

    def test_errors(self):
        FakeNtfy.mode = "error"
        with self.assertRaisesRegex(reminders.ReminderError, "HTTP 500"):
            reminders.send_ntfy(self.url, "sunak-abc123", "x", "y")
        FakeNtfy.mode = "redirect"  # never follows: the message must not go to another address
        with self.assertRaisesRegex(reminders.ReminderError, "HTTP 307"):
            reminders.send_ntfy(self.url, "sunak-abc123", "x", "y")
        with self.assertRaisesRegex(reminders.ReminderError, "Cannot reach"):
            reminders.send_ntfy("http://127.0.0.1:1", "sunak-abc123", "x", "y")
        self.assertEqual(reminders.ntfy_server(""), "https://ntfy.sh")


class ReminderServerTest(unittest.TestCase):
    call = classmethod(test_server.SunakTest.call.__func__)

    @classmethod
    def setUpClass(cls):
        FakeNtfy.mode = "ok"
        cls.ntfy = ThreadingHTTPServer(("127.0.0.1", 0), FakeNtfy)
        threading.Thread(target=cls.ntfy.serve_forever, daemon=True).start()
        cls.ntfy_url = f"http://127.0.0.1:{cls.ntfy.server_address[1]}"
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, os.path.join(cls.tmp.name, "data"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.app = cls.srv.RequestHandlerClass.app
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        for s in (cls.srv, cls.ntfy):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        FakeNtfy.posts, FakeNtfy.mode = [], "ok"
        for row in self.app.db.cal_events():
            self.app.db.cal_delete(row["uid"])
        self.app.db._q("DELETE FROM reminders_sent")
        self.app.reminders._cache.clear()
        self.call("PUT", "/api/settings", {"reminders": False, "ntfy_url": "", "ntfy_topic": ""})

    def error(self, *args, **kw):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(*args, **kw)
        return e.exception.code, json.loads(e.exception.read())["error"]

    def soon(self, minutes, reminder):
        start = dt.datetime.now(UTC).replace(microsecond=0) + dt.timedelta(minutes=minutes)
        iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        self.call("POST", "/api/calendar/events", {"event": {"summary": "Zahnarzt", "location": "Praxis", "start": iso(start),
                                                              "end": iso(start + dt.timedelta(hours=1)), "reminder": reminder}})

    def test_settings(self):
        s = self.call("GET", "/api/settings")
        self.assertEqual((s["reminders"], s["ntfy_url"], s["ntfy_topic"]), (False, "", ""))
        self.call("PUT", "/api/settings", {"reminders": True, "ntfy_url": " http://x.example ", "ntfy_topic": "sunak-abc123", "reminder_lang": "de"})
        s = self.call("GET", "/api/settings")
        self.assertEqual((s["reminders"], s["ntfy_url"], s["ntfy_topic"], s["reminder_lang"]), (True, "http://x.example", "sunak-abc123", "de"))
        self.assertIn("ntfy address", self.error("PUT", "/api/settings", {"ntfy_url": "ntfy.sh"})[1])
        self.assertIn("ntfy topic", self.error("PUT", "/api/settings", {"ntfy_topic": "my topic!"})[1])
        self.assertIn("reminder_lang", self.error("PUT", "/api/settings", {"reminder_lang": "xx"})[1])
        self.assertEqual(self.call("GET", "/api/export")["settings"]["ntfy_topic"], "")  # like a password: not in the backup

    def test_due_reminder_goes_out_once(self):
        self.soon(10, 15)
        self.soon(300, 15)  # far away: not yet
        self.call("PUT", "/api/settings", {"reminders": True, "ntfy_url": self.ntfy_url, "ntfy_topic": "sunak-abc123", "reminder_lang": "en"})
        self.app.reminders.tick()
        self.app.reminders.tick()
        self.assertEqual(len(FakeNtfy.posts), 1)
        post = FakeNtfy.posts[0]
        self.assertEqual((post["topic"], post["title"]), ("sunak-abc123", "Zahnarzt"))
        self.assertTrue(post["message"].startswith("Starts in 15 minutes (") and post["message"].endswith(") · Praxis"), post["message"])
        got = self.call("GET", "/api/reminders")["items"]
        self.assertEqual([(i["title"], i["text"].startswith("Starts in 15 minutes")) for i in got], [("Zahnarzt", True)])
        self.assertEqual(self.call("GET", "/api/reminders")["items"], [])  # handed out once

    def test_off_and_changed_events(self):
        self.soon(10, 15)
        self.app.reminders.tick()  # reminders are off
        self.assertEqual((FakeNtfy.posts, self.call("GET", "/api/reminders")["items"]), ([], []))
        self.call("PUT", "/api/settings", {"reminders": True})
        self.assertEqual(self.call("GET", "/api/reminders")["items"], [])  # the first look has not happened yet
        self.app.reminders.tick()  # no topic: only the page
        self.assertEqual((FakeNtfy.posts, len(self.call("GET", "/api/reminders")["items"])), ([], 1))
        self.soon(10, None)  # without a reminder nothing happens
        self.app.reminders.tick()
        self.assertEqual(self.call("GET", "/api/reminders")["items"], [])
        self.soon(10, 15)  # a new event is noticed at once (the list of events is read again)
        self.app.reminders.tick()
        self.assertEqual(len(self.call("GET", "/api/reminders")["items"]), 1)

    def test_page_gets_what_it_missed(self):
        """Nobody looked when the reminder fell due, and Sunak restarted meanwhile: the next page still gets it."""
        self.soon(10, 15)
        self.call("PUT", "/api/settings", {"reminders": True})
        self.app.reminders.tick()
        self.app.reminders._cache.clear()  # a restart forgets the events (the table of given reminders stays)
        self.assertEqual(self.call("GET", "/api/reminders")["items"], [])
        self.app.reminders.tick()
        self.assertEqual(len(self.call("GET", "/api/reminders")["items"]), 1)
        self.assertEqual(self.call("GET", "/api/reminders")["items"], [])
        # an event that has started is not announced any more
        past = dt.datetime.now(UTC) - dt.timedelta(minutes=1)
        self.app.db.cal_put("late@sunak", cal.build_event("late@sunak", "Vorbei", past, past + dt.timedelta(hours=1), False, reminder=15))
        self.app.reminders.invalidate("default")
        self.app.reminders.tick()
        self.assertEqual(self.call("GET", "/api/reminders")["items"], [])

    def test_deleted_profile_is_left_alone(self):
        self.app.reminders._cache["ghost"] = (0, [])
        self.app.reminders.tick()
        self.assertNotIn("ghost", self.app.reminders._cache)
        self.assertFalse(self.app.profile_dir("ghost").exists())

    def test_failing_push_is_tried_again(self):
        self.soon(10, 15)
        self.call("PUT", "/api/settings", {"reminders": True, "ntfy_url": self.ntfy_url, "ntfy_topic": "sunak-abc123"})
        FakeNtfy.mode = "error"
        self.app.reminders.tick()
        self.assertEqual(FakeNtfy.posts, [])
        self.assertEqual(len(self.call("GET", "/api/reminders")["items"]), 1)  # the page has it
        FakeNtfy.mode = "ok"
        self.app.reminders.tick()
        self.app.reminders.tick()
        self.assertEqual(len(FakeNtfy.posts), 1)
        self.assertEqual(self.call("GET", "/api/reminders")["items"], [])  # the page has had it once already

    def test_test_message(self):
        r = self.call("POST", "/api/reminders/test", {"ntfy_url": self.ntfy_url, "ntfy_topic": "sunak-abc123", "lang": "de"})
        self.assertEqual((r["pushed"], r["text"]), (True, "Erinnerungen funktionieren. Das ist ein Test."))
        self.assertEqual(FakeNtfy.posts[0]["message"], r["text"])
        self.assertFalse(self.call("POST", "/api/reminders/test", {})["pushed"])  # no topic: only the page shows it
        FakeNtfy.mode = "error"
        self.assertIn("HTTP 500", self.error("POST", "/api/reminders/test", {"ntfy_url": self.ntfy_url, "ntfy_topic": "sunak-abc123"})[1])
        self.assertIn("ntfy topic", self.error("POST", "/api/reminders/test", {"ntfy_topic": "no good"})[1])

    def test_event_form_roundtrip(self):
        self.soon(600, 30)
        evs = self.call("GET", "/api/calendar/events?" + "start=" + (dt.datetime.now(UTC) - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                        + "&end=" + (dt.datetime.now(UTC) + dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))["events"]
        self.assertEqual(evs[0]["alarms"], [30])


if __name__ == "__main__":
    unittest.main()
