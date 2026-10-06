"""Calendar: iCalendar parsing and recurrence, writing events, a simulated CalDAV server (discovery with
redirect, events, ETags), ICS subscriptions, Sunak's own calendar and reading events out of text."""

import base64
import datetime as dt
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sunak import cal
from sunak.server import make_server

import test_server

VTZ = """BEGIN:VTIMEZONE
TZID:{tzid}
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
"""

SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
""" + VTZ.format(tzid="Custom/Berlin") + """BEGIN:VEVENT
UID:w1
DTSTART;TZID=Custom/Berlin:20261019T090000
DTEND;TZID=Custom/Berlin:20261019T100000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6
EXDATE;TZID=Custom/Berlin:20261021T090000
SUMMARY:Standup\\, team
DESCRIPTION:Line 1\\nLine 2 is long enough that a calendar program would fold it onto a second
  line
END:VEVENT
BEGIN:VEVENT
UID:w1
RECURRENCE-ID;TZID=Custom/Berlin:20261026T090000
DTSTART;TZID=Custom/Berlin:20261026T110000
DTEND;TZID=Custom/Berlin:20261026T120000
SUMMARY:Standup moved
END:VEVENT
BEGIN:VEVENT
UID:a1
DTSTART;VALUE=DATE:20261024
DTEND;VALUE=DATE:20261026
SUMMARY:Weekend trip
END:VEVENT
BEGIN:VEVENT
UID:m1
DTSTART:20260131T100000Z
DURATION:PT30M
RRULE:FREQ=MONTHLY;BYMONTHDAY=-1
SUMMARY:Month end
END:VEVENT
BEGIN:VEVENT
UID:n1
DTSTART;VALUE=DATE:20261101
RRULE:FREQ=MONTHLY;BYDAY=1SU,-1FR;UNTIL=20261231
SUMMARY:First Sunday and last Friday
END:VEVENT
BEGIN:VEVENT
UID:c1
DTSTART:20261005T120000Z
SUMMARY:Cancelled one
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""

CEST, CET = dt.timezone(dt.timedelta(hours=2)), dt.timezone(dt.timedelta(hours=1))


def events(text, start, end):
    return sorted(cal.events_in(text, start, end, "x"), key=lambda e: e["start"])


class ICalendarTest(unittest.TestCase):
    def test_recurrence_and_time_zones(self):
        evs = events(SAMPLE, dt.datetime(2026, 10, 1, tzinfo=CEST), dt.datetime(2026, 12, 1, tzinfo=CET))
        got = [(e["start"], e["end"], e["summary"]) for e in evs]
        self.assertEqual(got, [
            ("2026-10-05T12:00:00Z", "2026-10-05T12:00:00Z", "Cancelled one"),
            ("2026-10-19T07:00:00Z", "2026-10-19T08:00:00Z", "Standup, team"),   # summer time
            ("2026-10-24", "2026-10-26", "Weekend trip"),
            ("2026-10-26T10:00:00Z", "2026-10-26T11:00:00Z", "Standup moved"),   # 21st left out, 26th moved
            ("2026-10-28T08:00:00Z", "2026-10-28T09:00:00Z", "Standup, team"),   # winter time
            ("2026-10-31T10:00:00Z", "2026-10-31T10:30:00Z", "Month end"),
            ("2026-11-01", "2026-11-02", "First Sunday and last Friday"),
            ("2026-11-02T08:00:00Z", "2026-11-02T09:00:00Z", "Standup, team"),
            ("2026-11-04T08:00:00Z", "2026-11-04T09:00:00Z", "Standup, team"),   # 6th and last (COUNT=6)
            ("2026-11-27", "2026-11-28", "First Sunday and last Friday"),
            ("2026-11-30T10:00:00Z", "2026-11-30T10:30:00Z", "Month end"),
        ])
        self.assertEqual(evs[1]["description"], "Line 1\nLine 2 is long enough that a calendar program would fold it onto a second line")
        self.assertEqual(evs[0]["status"], "cancelled")
        self.assertTrue(evs[1]["recurring"] and evs[3]["recurring"] and not evs[2]["all_day"] is False)
        dec = events(SAMPLE, dt.datetime(2026, 12, 1, tzinfo=CET), dt.datetime(2027, 2, 1, tzinfo=CET))
        self.assertEqual([e["start"] for e in dec if e["uid"] == "n1"], ["2026-12-06", "2026-12-25"])  # UNTIL
        self.assertEqual([e["start"][:10] for e in dec if e["uid"] == "m1"], ["2026-12-31", "2027-01-31"])

    def test_known_zone_names_match_the_calendars_own(self):
        """Europe/Berlin and the Windows name come from the system's zone database or, without one
        (Windows without tzdata), from the VTIMEZONE in the file; all must give the same times."""
        results = []
        for tzid in ("Europe/Berlin", "W. Europe Standard Time", "Custom/Berlin"):
            text = ("BEGIN:VCALENDAR\n" + VTZ.format(tzid=tzid) + f"BEGIN:VEVENT\nUID:z\nDTSTART;TZID={tzid}:20260315T090000\n"
                    "RRULE:FREQ=WEEKLY;COUNT=3\nSUMMARY:z\nEND:VEVENT\nEND:VCALENDAR\n")
            results.append([e["start"] for e in events(text, dt.datetime(2026, 3, 1, tzinfo=CET), dt.datetime(2026, 4, 30, tzinfo=CEST))])
        self.assertEqual(results[0], ["2026-03-15T08:00:00Z", "2026-03-22T08:00:00Z", "2026-03-29T07:00:00Z"])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_yearly_and_limits(self):
        text = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:b\nDTSTART;VALUE=DATE:19960229\nRRULE:FREQ=YEARLY\nSUMMARY:Leap\nEND:VEVENT\n"
                "BEGIN:VEVENT\nUID:d\nDTSTART:19900101T060000Z\nRRULE:FREQ=DAILY;INTERVAL=2\nSUMMARY:Old daily\nEND:VEVENT\n"
                "BEGIN:VEVENT\nUID:bad\nDTSTART:2026XX\nSUMMARY:Broken\nEND:VEVENT\nEND:VCALENDAR\n")
        y27 = events(text, dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc), dt.datetime(2027, 12, 31, tzinfo=dt.timezone.utc))
        self.assertEqual([e["uid"] for e in y27].count("b"), 0)  # no 29 February in 2027
        y28 = events(text, dt.datetime(2028, 2, 1, tzinfo=dt.timezone.utc), dt.datetime(2028, 3, 1, tzinfo=dt.timezone.utc))
        self.assertEqual([e["start"] for e in y28 if e["uid"] == "b"], ["2028-02-29"])
        self.assertEqual(len([e for e in y28 if e["uid"] == "d"]), 15)  # every second day of February 2028 (29 days)
        with self.assertRaises(cal.CalendarError):
            cal.parse("hello")

    def test_write_and_update(self):
        title = "Grillen mit Ömer; Bring: Würstchen, Brot \\ " + "lang " * 20
        start = dt.datetime(2026, 7, 4, 16, 0, tzinfo=dt.timezone.utc)
        text = cal.build_event("u1@sunak", title, start, start + dt.timedelta(hours=3), False, "Park", "Zeile 1\nZeile 2", "WEEKLY")
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))
        evs = events(text, dt.datetime(2026, 7, 1, tzinfo=CEST), dt.datetime(2026, 7, 20, tzinfo=CEST))
        self.assertEqual([e["start"] for e in evs], ["2026-07-04T16:00:00Z", "2026-07-11T16:00:00Z", "2026-07-18T16:00:00Z"])
        self.assertEqual((evs[0]["summary"], evs[0]["location"], evs[0]["description"]), (title, "Park", "Zeile 1\nZeile 2"))
        # changes keep what Sunak does not edit (reminder, guests)
        other = text.replace("END:VEVENT", "ATTENDEE;CN=\"Doe, Jane\":mailto:jane@example.com\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\n"
                             "TRIGGER:-PT15M\r\nEND:VALARM\r\nSEQUENCE:3\r\nEND:VEVENT")
        ev = cal.clean_event({"summary": "Neu", "start": "2026-07-05", "end": "2026-07-06", "all_day": True, "location": ""})
        changed = cal.update_event(other, "u1@sunak", ev)
        self.assertIn("TRIGGER:-PT15M", changed)
        self.assertIn('ATTENDEE;CN="Doe, Jane":mailto:jane@example.com', changed)
        self.assertIn("SEQUENCE:4", changed)
        self.assertNotIn("RRULE", changed)
        self.assertNotIn("LOCATION", changed)
        self.assertEqual([(e["start"], e["end"], e["summary"], e["all_day"]) for e in
                          events(changed, dt.datetime(2026, 7, 1, tzinfo=CEST), dt.datetime(2026, 7, 31, tzinfo=CEST))],
                         [("2026-07-05", "2026-07-06", "Neu", True)])
        series = cal.update_event(text, "u1@sunak", ev, times=False)  # a series keeps its times
        self.assertIn("RRULE:FREQ=WEEKLY", series)
        self.assertIn("DTSTART:20260704T160000Z", series)
        with self.assertRaises(cal.CalendarError):
            cal.update_event(text, "other", ev)

    def test_clean_event(self):
        ev = cal.clean_event({"summary": " Call ", "start": "2026-10-06T08:00:00.000Z", "end": "2026-10-06T10:30:00+02:00"})
        self.assertEqual((ev["summary"], ev["start"].isoformat(), ev["end"].isoformat()),
                         ("Call", "2026-10-06T08:00:00+00:00", "2026-10-06T08:30:00+00:00"))
        self.assertEqual(cal.clean_event({"summary": "Day", "start": "2026-10-06", "end": "2026-10-06", "all_day": True})["end"],
                         dt.date(2026, 10, 7))  # a one-day event ends the next day (exclusive)
        for bad, msg in [({"summary": "", "start": "2026-10-06"}, "title"),
                         ({"summary": "x", "start": "2026-10-06T08:00:00"}, "time zone"),
                         ({"summary": "x", "start": "2026-10-06", "all_day": False}, "both"),
                         ({"summary": "x", "start": "2026-10-06T08:00Z", "end": "2026-10-06T07:00Z"}, "ends before"),
                         ({"summary": "x", "start": "2026-10-06T08:00Z", "repeat": "HOURLY"}, "repeat")]:
            with self.assertRaisesRegex(ValueError, msg):
                cal.clean_event(bad)

    def test_parse_answer(self):
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=CEST)
        self.assertEqual(cal.parse_answer('Sure!\n```json\n{"summary": "Zahnarzt", "start": "2026-10-13T10:00", "end": null}\n```', now),
                         {"summary": "Zahnarzt", "start": "2026-10-13T10:00", "end": "2026-10-13T11:00", "all_day": False,
                          "location": "", "description": ""})
        self.assertEqual(cal.parse_answer('{"summary": "Urlaub", "start": "2026-10-20", "end": "2026-10-24", "location": "Rom"}', now)
                         ["end"], "2026-10-24")
        self.assertEqual(cal.parse_answer('{"summary": "x", "start": "2026-10-20 18:30:00+02:00"}', now)["start"], "2026-10-20T18:30")
        for bad in ("no json", '{"summary": "x"}', '{"summary": "x", "start": "next week"}', '{"summary": "x", "start": "2026-13-40"}'):
            with self.assertRaises(ValueError):
                cal.parse_answer(bad, now)
        msgs = cal.parse_messages("Dentist next Tuesday", now)
        self.assertIn("Tuesday, 2026-10-06 09:00 (UTC+02:00)", msgs[0]["content"])


# a CalDAV server ------------------------------------------------------------------------------

def ms(responses):
    out = ['<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="http://apple.com/ns/ical/">']
    for href, props in responses:
        out.append(f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
                   "<d:propstat><d:prop><d:getctag/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat></d:response>")
    return "".join(out) + "</d:multistatus>"


class CalDAV(BaseHTTPRequestHandler):
    store, log, n = {}, [], 0
    password = "pw"

    def log_message(self, *a):
        pass

    def reply(self, code, body=b"", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except ConnectionError:
            pass

    def auth(self):
        expected = "Basic " + base64.b64encode(f"max@example.com:{CalDAV.password}".encode()).decode()
        if self.headers.get("Authorization") != expected:
            self.reply(401, "no", {"WWW-Authenticate": 'Basic realm="x"'})
            return False
        return True

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()

    def do_PROPFIND(self):
        body = self.body()
        CalDAV.log.append(("PROPFIND", self.path, self.headers.get("Depth")))
        if self.path == "/":
            return self.reply(301, "", {"Location": "/dav/"})  # like a provider moving its CalDAV root
        if not self.auth():
            return
        if self.path == "/dav/":
            return self.reply(207, ms([("/dav/", "<d:current-user-principal><d:href>/principals/max/</d:href></d:current-user-principal>")]))
        if self.path == "/principals/max/":
            return self.reply(207, ms([(self.path, "<c:calendar-home-set><d:href>/cals/max/</d:href></c:calendar-home-set>")]))
        if self.path == "/cals/max/" and "displayname" in body:
            return self.reply(207, ms([
                ("/cals/max/", "<d:resourcetype><d:collection/></d:resourcetype>"),
                ("/cals/max/work/", "<d:displayname>Work</d:displayname><a:calendar-color>#FF0000FF</a:calendar-color>"
                 "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                 '<c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>'),
                ("/cals/max/tasks/", "<d:displayname>Tasks</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                 '<c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>')]))
        self.reply(404)

    def do_REPORT(self):
        body = self.body()
        CalDAV.log.append(("REPORT", self.path, body))
        if not self.auth():
            return
        items = [(p, e, t) for p, (e, t) in sorted(CalDAV.store.items()) if p.startswith(self.path)]
        self.reply(207, ms([(p, f'<d:getetag>{e}</d:getetag><c:calendar-data>{t.replace("&", "&amp;").replace("<", "&lt;")}</c:calendar-data>')
                            for p, e, t in items]))

    def do_GET(self):
        if self.path == "/feed.ics":
            return self.reply(200, "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:h1\r\nDTSTART;VALUE=DATE:20261003\r\nSUMMARY:Holiday\r\n"
                              "END:VEVENT\r\nEND:VCALENDAR\r\n", {"Content-Type": "text/calendar"})
        if self.path == "/not-a-calendar":
            return self.reply(200, "<html>hi</html>")
        if not self.auth():
            return
        if self.path not in CalDAV.store:
            return self.reply(404)
        etag, text = CalDAV.store[self.path]
        self.reply(200, text, {"ETag": etag})

    def do_PUT(self):
        text = self.body()
        if not self.auth():
            return
        CalDAV.log.append(("PUT", self.path, self.headers.get("If-Match"), self.headers.get("If-None-Match")))
        cur = CalDAV.store.get(self.path)
        if self.headers.get("If-None-Match") == "*" and cur or self.headers.get("If-Match") and (not cur or cur[0] != self.headers["If-Match"]):
            return self.reply(412)
        CalDAV.n += 1
        CalDAV.store[self.path] = (f'"e{CalDAV.n}"', text)
        self.reply(201 if not cur else 204, b"", {"ETag": f'"e{CalDAV.n}"'})

    def do_DELETE(self):
        if not self.auth():
            return
        cur = CalDAV.store.get(self.path)
        if not cur:
            return self.reply(404)
        if self.headers.get("If-Match") and cur[0] != self.headers["If-Match"]:
            return self.reply(412)
        del CalDAV.store[self.path]
        self.reply(204)

    def do_POST(self):  # the model for "✨": an Ollama-style chat endpoint
        self.body()
        line = json.dumps({"message": {"content": '{"summary": "Zahnarzt", "start": "2026-10-13T10:00", "location": "Praxis"}'}, "done": True})
        self.reply(200, line + "\n", {"Content-Type": "application/x-ndjson"})


class CalendarServerTest(unittest.TestCase):
    call = classmethod(test_server.SunakTest.call.__func__)

    @classmethod
    def setUpClass(cls):
        cls.dav = ThreadingHTTPServer(("127.0.0.1", 0), CalDAV)
        threading.Thread(target=cls.dav.serve_forever, daemon=True).start()
        cls.dav_url = f"http://127.0.0.1:{cls.dav.server_address[1]}"
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.srv = make_server("127.0.0.1", 0, os.path.join(cls.tmp.name, "data"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.app = cls.srv.RequestHandlerClass.app
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.call("PUT", "/api/settings", {"providers": [{"id": "ollama", "name": "Ollama", "type": "ollama", "base_url": cls.dav_url}]})

    @classmethod
    def tearDownClass(cls):
        for s in (cls.srv, cls.dav):
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        CalDAV.store.clear()
        CalDAV.log.clear()
        CalDAV.password = "pw"
        self.app.db.set_setting("calendars", [])
        self.app.db.set_setting("mail_accounts", [])

    def error(self, *args, **kw):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(*args, **kw)
        return e.exception.code, json.loads(e.exception.read())["error"]

    def range(self, start="2026-10-01T00:00:00+02:00", end="2026-11-01T00:00:00+01:00"):
        q = urllib.parse.urlencode({"start": start, "end": end})
        return self.call("GET", f"/api/calendar/events?{q}")

    def caldav(self, **extra):
        src = {"type": "caldav", "name": "Work account", "url": self.dav_url + "/", "username": "max@example.com", "password": "pw", **extra}
        return self.call("POST", "/api/calendar/sources", {"source": src})

    def test_local_calendar(self):
        info = self.call("GET", "/api/calendar")
        self.assertEqual(info["sources"], [{"id": "local", "type": "local", "name": "Sunak", "color": "", "enabled": True}])
        self.assertIn("icloud", info["presets"])
        self.call("POST", "/api/calendar/events", {"event": {"summary": "Sport", "start": "2026-10-05T16:00:00Z",
                                                              "end": "2026-10-05T17:00:00Z", "repeat": "WEEKLY"}})
        self.call("POST", "/api/calendar/events", {"source": "local", "event": {"summary": "Trip", "start": "2026-10-10",
                                                                                "end": "2026-10-12", "all_day": True}})
        evs = self.range()["events"]
        self.assertEqual([(e["summary"], e["start"]) for e in evs],
                         [("Sport", "2026-10-05T16:00:00Z"), ("Trip", "2026-10-10"), ("Sport", "2026-10-12T16:00:00Z"),
                          ("Sport", "2026-10-19T16:00:00Z"), ("Sport", "2026-10-26T16:00:00Z")])
        trip = evs[1]
        self.assertEqual((trip["end"], trip["writable"], trip["source"]), ("2026-10-12", True, "local"))
        self.call("PUT", "/api/calendar/events", {"source": "local", "uid": trip["uid"], "event": {
            "summary": "Trip to Rome", "start": "2026-10-10", "end": "2026-10-13", "all_day": True, "location": "Rome"}})
        sport = evs[0]
        self.call("PUT", "/api/calendar/events", {"source": "local", "uid": sport["uid"], "recurring": True, "event": {
            "summary": "Running", "start": "2026-10-20T10:00:00Z", "end": "2026-10-20T11:00:00Z"}})
        evs = self.range()["events"]
        self.assertEqual([(e["summary"], e["start"], e["end"]) for e in evs][:3],
                         [("Running", "2026-10-05T16:00:00Z", "2026-10-05T17:00:00Z"), ("Trip to Rome", "2026-10-10", "2026-10-13"),
                          ("Running", "2026-10-12T16:00:00Z", "2026-10-12T17:00:00Z")])  # a series keeps its times
        self.call("POST", "/api/calendar/events/delete", {"source": "local", "uid": sport["uid"]})
        self.assertEqual([e["summary"] for e in self.range()["events"]], ["Trip to Rome"])
        backup = self.call("GET", "/api/export")
        self.assertIn("Trip to Rome", json.dumps(backup["calendar"]))

    def test_caldav_account(self):
        src = self.caldav()
        self.assertEqual(src["calendars"], [{"href": f"{self.dav_url}/cals/max/work/", "name": "Work", "color": "#FF0000", "enabled": True}])
        self.assertEqual(("password" in src, src["has_password"]), (False, True))
        self.assertNotIn('"pw"', self.call("GET", "/api/calendar", raw=True))
        self.assertNotIn('"pw"', self.call("GET", "/api/export", raw=True))
        work = src["calendars"][0]["href"]
        self.call("POST", "/api/calendar/events", {"source": src["id"], "calendar": work, "event": {
            "summary": "Review", "start": "2026-10-07T08:00:00Z", "end": "2026-10-07T09:00:00Z"}})
        (path, (etag, text)), = CalDAV.store.items()
        self.assertTrue(path.startswith("/cals/max/work/") and path.endswith("-sunak.ics"))
        self.assertIn(("PUT", path, None, "*"), CalDAV.log)
        res = self.range()
        self.assertEqual(res["errors"], [])
        ev, = res["events"]
        self.assertEqual((ev["summary"], ev["href"], ev["etag"], ev["calendar"], ev["color"]),
                         ("Review", self.dav_url + path, etag, work, "#FF0000"))
        report = next(x for x in CalDAV.log if x[0] == "REPORT")[2]
        self.assertIn('<c:time-range start="20260930T220000Z" end="20261031T230000Z"/>', report)
        change = {"source": src["id"], "uid": ev["uid"], "href": ev["href"], "etag": ev["etag"],
                  "event": {"summary": "Review v2", "start": "2026-10-07T09:00:00Z", "end": "2026-10-07T10:00:00Z"}}
        self.call("PUT", "/api/calendar/events", change)
        self.assertIn("SUMMARY:Review v2", CalDAV.store[path][1])
        self.assertIn(("PUT", path, etag, None), CalDAV.log)
        code, err = self.error("PUT", "/api/calendar/events", change)  # the old ETag: changed elsewhere meanwhile
        self.assertEqual((code, "changed elsewhere" in err), (400, True))
        code, err = self.error("POST", "/api/calendar/events/delete", dict(change, href="http://evil.example/x.ics"))
        self.assertIn("Unknown event address", err)
        self.error("POST", "/api/calendar/events/delete", dict(change, href=work + "../../other/x.ics"))
        self.call("POST", "/api/calendar/events/delete", dict(change, etag=CalDAV.store[path][0]))
        self.assertEqual(CalDAV.store, {})
        # the password stays when the form sends none
        again = self.caldav(id=src["id"], password="", calendars=[dict(src["calendars"][0], enabled=False)])
        self.assertEqual((again["id"], again["calendars"][0]["enabled"]), (src["id"], False))
        self.assertEqual(self.app.calendars()[0]["password"], "pw")
        self.assertEqual(self.range()["events"], [])  # that calendar is hidden now
        CalDAV.password = "new"
        self.assertIn("did not accept", self.error("POST", "/api/calendar/sources", {"source": dict(again, password="")})[1])
        self.caldav(id=src["id"], password="new")
        self.assertEqual(self.app.calendars()[0]["password"], "new")
        CalDAV.password = "other"
        self.assertIn("did not accept", self.error("POST", "/api/calendar/sources", {"source": dict(again, password="wrong")})[1])

    def test_caldav_errors_and_mail_password(self):
        self.assertIn("did not accept", self.error("POST", "/api/calendar/sources", {"source": {
            "type": "caldav", "url": self.dav_url + "/", "username": "max@example.com", "password": "nope"}})[1])
        self.assertIn("Enter the password", self.error("POST", "/api/calendar/sources", {"source": {
            "type": "caldav", "url": self.dav_url + "/", "username": "max@example.com"}})[1])
        self.assertIn("not reach", self.error("POST", "/api/calendar/sources", {"source": {
            "type": "caldav", "url": "http://127.0.0.1:9/", "username": "u", "password": "p"}})[1])
        self.app.db.set_setting("mail_accounts", [{"id": "m1", "email": "max@example.com", "password": "pw", "imap_host": "x"}])
        src = self.call("POST", "/api/calendar/sources", {"source": {
            "type": "caldav", "url": self.dav_url + "/", "username": "max@example.com", "mail_account": "m1"}})
        self.assertEqual((src["has_password"], src["mail_account"]), (False, "m1"))
        info = self.call("GET", "/api/calendar")
        self.assertEqual(info["mail_accounts"], [{"id": "m1", "email": "max@example.com", "preset": ""}])
        self.app.db.set_setting("mail_accounts", [{"id": "m1", "email": "max@example.com", "password": "pw", "imap_host": "imap.gmx.net"},
                                                  {"id": "m2", "email": "a@icloud.com", "password": "x", "imap_host": "imap.mail.me.com"}])
        self.assertEqual([m["preset"] for m in self.call("GET", "/api/calendar")["mail_accounts"]], ["gmx", "icloud"])
        CalDAV.store["/cals/max/work/x.ics"] = ('"e0"', "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART:20261002T100000Z\r\n"
                                                         "SUMMARY:From the server\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        self.assertEqual([e["summary"] for e in self.range()["events"]], ["From the server"])
        self.app.db.set_setting("mail_accounts", [])  # the mail account is gone: the calendar reports an error
        res = self.range()
        self.assertEqual((res["events"], res["errors"][0]["name"]), ([], "Work"))

    def test_ics_subscription(self):
        src = self.call("POST", "/api/calendar/sources", {"source": {"type": "ics", "name": "Holidays", "url": self.dav_url + "/feed.ics"}})
        ev, = self.range()["events"]
        self.assertEqual((ev["summary"], ev["writable"], ev["source"], ev["color"]), ("Holiday", False, src["id"], src["color"]))
        self.assertIn("read-only", self.error("POST", "/api/calendar/events", {"source": src["id"], "event": {
            "summary": "x", "start": "2026-10-03", "all_day": True}})[1])
        self.assertIn("not a calendar", self.error("POST", "/api/calendar/sources", {"source": {
            "type": "ics", "url": self.dav_url + "/not-a-calendar"}})[1])
        self.call("DELETE", f"/api/calendar/sources/{src['id']}")
        self.assertEqual(self.range()["events"], [])
        self.assertIn("about a year", self.error("GET", "/api/calendar/events?start=2026-01-01T00:00Z&end=2028-01-01T00:00Z")[1])
        self.assertEqual(self.error("GET", "/api/calendar/events?start=2026-01-01&end=x")[0], 400)

    def test_parse_with_the_model(self):
        res = self.call("POST", "/api/calendar/parse", {"text": "Zahnarzt nächsten Dienstag 10 Uhr", "now": "2026-10-06T09:00:00+02:00",
                                                        "model": "ollama::fake"})
        self.assertEqual(res, {"summary": "Zahnarzt", "start": "2026-10-13T10:00", "end": "2026-10-13T11:00", "all_day": False,
                               "location": "Praxis", "description": ""})
        self.assertEqual(self.error("POST", "/api/calendar/parse", {"text": " ", "now": "2026-10-06T09:00:00+02:00"})[0], 400)


if __name__ == "__main__":
    unittest.main()
