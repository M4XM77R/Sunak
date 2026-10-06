"""`sunak mail-selftest`: try a real mail account (e.g. Gmail with an app password) end to end, the way Sunak
uses it: log in, read, notice new mail, send with an attachment, receive it, forward its attachment, move,
delete. Only the self-test's own messages are touched: each has a random token in its subject, every hit is
checked against the full token, and they are removed at the end (Trash, then for good). The password is never
printed."""

import base64
import contextlib
import email
import email.policy
import getpass
import os
import secrets
import sys
import time
from pathlib import Path

from . import mail
from .db import DB


class Step:
    """Counts and prints the results: ✓ passed, ✗ failed, ! warning (works, but worth knowing)."""

    def __init__(self, out):
        self.out, self.failed, self.warned = out, 0, 0

    def ok(self, what, detail=""):
        self.out(f"  ✓ {what}" + (f": {detail}" if detail else ""))

    def fail(self, what, detail):
        self.failed += 1
        self.out(f"  ✗ {what}: {detail}")

    def warn(self, what, detail):
        self.warned += 1
        self.out(f"  ! {what}: {detail}")


def _wait_find(acc, folders, subject, seconds, poll=3.0):
    """(folder, uid) of the first message with `subject` in one of `folders`, waiting up to `seconds`."""
    end = time.monotonic() + seconds
    while True:
        with mail.imap(acc) as conn:
            for f in folders:
                uids = mail.find(conn, f, subject)
                if uids:
                    return f, uids[-1]
        if time.monotonic() >= end:
            return None, None
        time.sleep(poll)


def cleanup(acc, token, folders, poll=2.0):
    """Remove every message whose subject contains `token`: into the Trash, then for good. Returns the count."""
    trash = next((f["id"] for f in folders if f["role"] == "trash"), None)
    removed = 0
    with mail.imap(acc) as conn:
        for f in folders:
            if f["id"] == trash:
                continue
            uids = mail.find(conn, f["id"], token)
            if uids:
                seq = ",".join(map(str, uids))
                if trash:
                    mail._move(conn, f["id"], seq, trash)
                else:
                    caps = mail._capabilities(conn)
                    mail._select_rw(conn, f["id"])
                    typ, data = conn.uid("STORE", seq, "+FLAGS.SILENT", "(\\Deleted)")
                    mail._check(typ, data, "Could not delete the test messages")
                    mail._expunge(conn, seq, caps)
                    removed += len(uids)
    if trash:
        # Gmail moves into the Trash with a short delay; look a few times
        for _ in range(5):
            with mail.imap(acc) as conn:
                uids = mail.find(conn, trash, token)
            if uids:
                mail.delete(acc, trash, uids, permanent=True)
                removed += len(uids)
                time.sleep(poll)
            else:
                break
    return removed


def run(acc, out=print, keep=False, wait=90, poll=3.0):
    """Run every step against `acc` (a saved account with its password). Returns the exit code: 0 when all passed."""
    s = Step(out)
    token = "sunak-selftest-" + secrets.token_hex(4)
    me = acc["email"]
    out(f"Self-test of {me} (IMAP {acc['imap_host']}:{acc['imap_port']}, SMTP {acc['smtp_host']}:{acc['smtp_port']}), "
        f"test messages are marked {token}")
    try:
        folders = mail.list_folders(acc)
    except mail.MailError as e:
        s.fail("IMAP login", e)
        return 1
    roles = {f["role"]: f for f in folders if f["role"]}
    s.ok("IMAP login and folders", ", ".join(f"{r}={roles[r]['name']}" for r in
                                             ("inbox", "sent", "drafts", "trash", "junk", "all") if r in roles))
    trash = roles.get("trash", {}).get("id")
    if not trash:
        s.warn("Trash folder", "not found, Delete in Sunak will delete for good (after asking)")

    try:
        listing = mail.list_messages(acc, "INBOX", limit=5)
        detail = f"{listing['total']} messages"
        if listing["messages"]:
            newest = listing["messages"][0]
            m = mail.get_message(acc, "INBOX", newest["uid"])
            detail += f", newest read without marking it as read ({len(m['text'])} characters)"
        s.ok("Read the Inbox", detail)
    except mail.MailError as e:
        s.fail("Read the Inbox", e)

    try:
        smtp = mail.smtp_login(acc)
        with contextlib.suppress(Exception):
            smtp.quit()
        s.ok("SMTP login")
    except mail.MailError as e:
        s.fail("SMTP login", e)

    # new-mail notice: put an unread message into the Inbox, as if it had just arrived
    new_subject = f"{token} new mail"
    try:
        before = mail.check_new(acc)
        msg = mail.build_message(acc, {"to": me, "subject": new_subject, "body": "Sunak self-test: new-mail notice."})
        with mail.imap(acc) as conn:
            mail._append(conn, "INBOX", "", msg)
        found = None
        for _ in range(5):
            after = mail.check_new(acc)
            found = next((m for m in after["latest"] if new_subject in m["subject"]), None)
            if found:
                break
            time.sleep(poll)
        if found:
            s.ok("New-mail notice", f"{before['unseen']} → {after['unseen']} unread, the new one is listed")
        else:
            s.fail("New-mail notice", "the unread test message did not show up")
    except mail.MailError as e:
        s.fail("New-mail notice", e)

    # move: Inbox → Trash (Delete in Sunak) → back to the Inbox (Move)
    try:
        if not trash:
            s.warn("Move and delete", "skipped, no Trash folder")
        else:
            folder, uid = _wait_find(acc, ["INBOX"], new_subject, 15, poll)
            if not uid:
                raise mail.MailError("test message not found in the Inbox")
            mail.delete(acc, "INBOX", [uid])
            folder, uid = _wait_find(acc, [trash], new_subject, 20, poll)
            if not uid:
                raise mail.MailError(f"test message not found in {roles['trash']['name']} after deleting")
            mail.move(acc, trash, [uid], "INBOX")
            folder, uid = _wait_find(acc, ["INBOX"], new_subject, 20, poll)
            if not uid:
                raise mail.MailError("test message did not come back into the Inbox")
            s.ok("Delete into the Trash and move back", f"Inbox → {roles['trash']['name']} → Inbox")
    except mail.MailError as e:
        s.fail("Move and delete", e)

    # send to yourself with an attachment, receive it, compare the attachment
    payload = secrets.token_bytes(3000) + "Grüße".encode()
    file_name = "sunak-prüfung.bin"
    send_subject = f"{token} send"
    got = (None, None)
    try:
        r = mail.send(acc, {"to": me, "subject": send_subject, "body": "Sunak self-test: sending with an attachment.",
                            "attachments": [{"name": file_name, "data": base64.b64encode(payload).decode()}]})
        s.ok("Send over SMTP with an attachment", f"copy saved in {r['saved_to']}" if r["saved_to"] else
             "the provider keeps the copy in Sent itself")
        if r["warning"]:
            s.warn("Sent copy", r["warning"])
        out(f"    waiting up to {wait} s for it to arrive …")
        got = _wait_find(acc, ["INBOX"], send_subject, wait, poll)
        if got[1]:
            s.ok("Received in the Inbox")
        else:
            other = [roles[r]["id"] for r in ("all", "junk") if r in roles]
            got = _wait_find(acc, other, send_subject, 0, poll)
            if got[1]:
                s.warn("Received", f"not in the Inbox but in {mail.utf7_decode(got[0])} (some providers file mails to "
                                   "yourself there)")
            else:
                s.fail("Received", f"not there after {wait} s")
    except mail.MailError as e:
        s.fail("Send over SMTP with an attachment", e)

    if got[1]:
        try:
            m = mail.get_message(acc, got[0], got[1])
            names = [a["name"] for a in m["attachments"]]
            if file_name not in names:
                raise mail.MailError(f"attachment missing (found: {', '.join(names) or 'none'})")
            index = names.index(file_name)
            _, data = mail.get_attachment(acc, got[0], got[1], index)
            if data != payload:
                raise mail.MailError("the attachment came back changed")
            s.ok("Attachment received unchanged", f"{file_name}, {len(data)} bytes")
            # forward with the original attachment, stored as a draft (nothing more is sent)
            fwd_subject = f"{token} forward"
            folder = mail.save_draft(acc, {"to": me, "subject": fwd_subject, "body": "Sunak self-test: forwarding.",
                                           "forward": {"folder": got[0], "uid": got[1], "attachments": [index]}})
            drafts = roles.get("drafts", {}).get("id", "Drafts")
            d_folder, d_uid = _wait_find(acc, [drafts], fwd_subject, 20, poll)
            if not d_uid:
                raise mail.MailError(f"the forwarded draft is not in {folder}")
            with mail.imap(acc) as conn:
                _, raw = mail._fetch_raw(conn, d_folder, d_uid, mail.MAX_FULL)
            parts = list(email.message_from_bytes(raw, policy=email.policy.default).iter_attachments())
            if not any(p.get_filename() == file_name and p.get_payload(decode=True) == payload for p in parts):
                raise mail.MailError("the forwarded draft lacks the original attachment")
            s.ok("Forward with the original attachment", f"saved as a draft in {folder}")
        except mail.MailError as e:
            s.fail("Attachment and forward", e)

    if keep:
        out(f"  Test messages kept (--keep): search for {token}")
    else:
        try:
            n = cleanup(acc, token, mail.list_folders(acc), poll)
            s.ok("Deleted the test messages for good" if trash else "Deleted the test messages", f"{n} removed")
        except mail.MailError as e:
            s.fail("Clean up", f"{e}. Delete the messages with {token} in the subject by hand")

    out("")
    if s.failed:
        out(f"{s.failed} step(s) failed" + (f", {s.warned} warning(s)" if s.warned else "") + ".")
        return 1
    out("Everything works" + (f" ({s.warned} warning(s), see above)." if s.warned else "."))
    return 0


# command line -------------------------------------------------------------
def saved_accounts(data_dir):
    """[(profile name, account)] of every profile in `data_dir`, read from the databases (never changed)."""
    data_dir = Path(data_dir)
    main_db = data_dir / "sunak.db"
    if not main_db.exists():
        return []
    out = []
    main = DB(str(main_db))
    try:
        profiles = main.get_setting("profiles") or []
        out += [("", a) for a in main.get_setting("mail_accounts") or []]
    finally:
        main.close()
    for p in profiles:
        path = data_dir / "profiles" / str(p.get("id", "")) / "sunak.db"
        if p.get("id") not in (None, "", "default") and path.exists():
            db = DB(str(path))
            try:
                out += [(p.get("name") or p["id"], a) for a in db.get_setting("mail_accounts") or []]
            finally:
                db.close()
    return out


def ask_account(email_addr, read=input, secret=getpass.getpass):
    """An account typed in now (not saved): the address, its provider preset and the app password."""
    addr = email_addr or read("E-mail address: ").strip()
    pid = mail.preset_for(addr)
    if not pid:
        raise mail.MailError("Unknown provider: add the account in Sunak (Settings → Mail accounts) and run "
                             "sunak mail-selftest --account " + (addr or "ADDRESS"))
    p = mail.PRESETS[pid]
    print(f"{p['title']}: {p['help']}" + (f" {p['link']}" if p["link"] else ""))
    pw = secret("App password (not shown): ")
    if pid == "gmail":
        pw = pw.replace(" ", "")  # Google shows it in groups of four
    form = {k: p[k] for k in ("imap_host", "imap_port", "imap_security", "smtp_host", "smtp_port", "smtp_security",
                              "save_sent")}
    return mail.clean_account(dict(form, email=addr, password=pw), [], lambda: "selftest")


def main(argv):
    """sunak mail-selftest [--account EMAIL] [--data-dir PATH] [--keep] [--yes]"""
    args = list(argv)
    opts = {"--account": "", "--data-dir": os.environ.get("SUNAK_DATA", str(Path.home() / ".sunak"))}
    flags = set()
    while args:
        a = args.pop(0)
        if a in opts and args:
            opts[a] = args.pop(0)
        elif a in ("--keep", "--yes", "--new"):
            flags.add(a)
        else:
            print(f"Unknown option '{a}'. Usage: sunak mail-selftest [--account EMAIL] [--new] [--data-dir PATH] "
                  "[--keep] [--yes]", file=sys.stderr)
            return 2
    want = opts["--account"].lower()
    try:
        found = [] if "--new" in flags else saved_accounts(opts["--data-dir"])
        if want:
            found = [x for x in found if x[1]["email"].lower() == want]
        if len(found) > 1:
            print("Several accounts are linked; choose one with --account:", file=sys.stderr)
            for prof, a in found:
                print(f"  {a['email']}" + (f" (profile {prof})" if prof else ""), file=sys.stderr)
            return 2
        if found:
            acc = found[0][1]
            print(f"Using the saved account {acc['email']} (password from Sunak's settings).")
        else:
            if not sys.stdin.isatty():
                print("No saved account found. Run it in a terminal to type in the address and an app password, "
                      "or link the account in Sunak first.", file=sys.stderr)
                return 2
            print("No saved account" + (f" {want}" if want else "") + ": type one in (it is not saved).")
            acc = ask_account(want)
    except mail.MailError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print()
        return 130
    if "--yes" not in flags:
        print(f"The test sends one e-mail to {acc['email']} itself and adds two test messages (an unread one and a "
              "draft). At the end it deletes them for good. Nothing else in the mailbox is touched.")
        try:
            if input("Continue? [y/N] ").strip().lower() not in ("y", "yes", "j", "ja"):
                return 1
        except (KeyboardInterrupt, EOFError):
            print()
            return 130
    try:
        return run(acc, keep="--keep" in flags)
    except KeyboardInterrupt:
        print("\nStopped. Test messages may be left: search for sunak-selftest in your mailbox.")
        return 130
