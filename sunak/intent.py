"""Does a chat message ask for a picture? ("Generiere ein Bild von einem Fuchs", "mal mir eine Katze", "draw me a cat")

`classify` answers with rules: "yes" (clearly a request to make a picture), "no" (nothing to do with pictures), or
"maybe" (it could be, for example "Zeichne einen Drachen" with no picture word, or a question like "Wie erstelle ich ein
Bild in Photoshop?"). For "maybe" the server asks the chat model (`messages`, `parse`) when pictures are set up.
`subject` is the description without the request words, the fallback when the chat model cannot improve the prompt."""

import re

F = re.I
NOUN = (r"(?:bild(?:e|er|es|chen)?|foto(?:s|grafie|grafien)?|grafik(?:en)?|zeichnung(?:en)?|illustrations?|illustrationen|gemälde|"
        r"poster|logos?|wallpapers?|hintergrundbild(?:er)?|pictures?|images?|photos?|photographs?|drawings?|paintings?|"
        r"artworks?|sketch(?:es)?|portraits?|porträts?)")
VERB = (r"(?:generier\w*|erzeug\w*|erstell\w*|erschaff\w*|mach\w*|mal\w*|zeichn\w*|gestalt\w*|entwirf\w*|entwerf\w*|visualisier\w*|"
        r"illustrier\w*|skizzier\w*|generat\w*|creat\w*|mak\w*|draw\w*|paint\w*|sketch\w*|illustrat\w*|render\w*|produc\w*|design\w*)")
STRONG = re.compile(rf"\b{VERB}\b[^.?!\n]{{0,50}}?\b{NOUN}\b", F)
AFTER = re.compile(rf"\b{NOUN}\b[^.!\n]{{0,120}}?\b{VERB}\b", F)
FIRST_PERSON = re.compile(rf"\b(?:ich|wir|i|we)\s+(?:\w+\s+){{0,2}}?{VERB}\b", F)  # "ich mache ein Foto" tells, it does not ask
POLITE = re.compile(r"^\W*(?:bitte|please|kannst du|könntest du|kannst du mir|könntest du mir|können sie|can you|could you|would you|will you)\b", F)
HAS_NOUN = re.compile(rf"\b{NOUN}\b", F)
QUESTION = re.compile(r"^\W*(?:wie|was|warum|wieso|weshalb|wann|wo|wer|welche\w*|wozu|how|what|why|when|where|which|who)\b", F)
TECH = re.compile(r"\b(?:skript\w*|script\w*|code|python|funktion\w*|function\w*|programm\w*|css|html|javascript|api|docker|"
                  r"photoshop|gimp|software|befehl\w*|command\w*|bibliothek\w*|library|bildschirm\w*|screenshot\w*)\b", F)
DRAW_START = re.compile(
    r"^\W*(?:(?:bitte|please|kannst du(?: mir)?|könntest du(?: mir)?|can you|could you|would you|will you)\s+)*"
    r"(?:mal(?:e|st)?\b(?!\s+(?:ehrlich|sehen|kurz|schauen|eben|wieder|was|ganz|nach|mal|ob|wie|wer|in|im|zeit|\d))|"
    r"zeichn\w*|skizzier\w*|visualisier\w*|illustrier\w*|entwirf\w*|erschaff\w*|"
    r"(?:draw|paint|sketch|visuali[sz]e|illustrate|render|imagine)\b)", F)
REQUEST = re.compile(r"\b(?:ich (?:hätte|brauche|möchte|will|wünsche|wäre|würde)|zeig\w*|gib|hol|show|give|get|"
                     r"i (?:want|need|would like|d like)|bitte|please)\b", F)
LEAD_NOUN = re.compile(rf"^\W*{NOUN}\s*(?:[:\-–,]|\s(?:von|vom|of|mit|with|showing)\b)", F)
# short forms without a verb: "a picture of: a snowy landscape", "Bild von einem Fuchs", "image of a cat"
LEAD_SHORT = re.compile(rf"^\W*(?:(?:a|an|the|ein|eine|einen|das|ein)\s+)?{NOUN}\s*(?:[:\-–]|\s(?:von|vom|of|mit|with|showing)\b)\W*\w[\s\S]{{2,}}$", F)
# a direct order to draw: "draw a cat", "zeichne einen Drachen", "mal mir eine Katze"
DRAW_DIRECT = re.compile(r"^\W*(?:(?:bitte|please)\s+)?(?:(?:draw|paint|sketch)\s+(?:me\s+)?(?:an?|the|some)\b|zeichne\w*\s+(?:mir\s+)?(?:ein\w*|den|die|das)\b|skizzier\w*\s+(?:mir\s+)?ein\w*|male?\s+mir\b|mal\s+mir\b)", F)
MAX_LENGTH = 600


def classify(text):
    """"yes", "maybe" or "no" for a chat message."""
    t = (text or "").strip()
    if not t or len(t) > MAX_LENGTH:
        return "no"
    draw = DRAW_START.search(t)
    if not draw and not HAS_NOUN.search(t):
        return "no"
    unsure = QUESTION.search(t) or TECH.search(t) or FIRST_PERSON.search(t)
    if STRONG.search(t):
        return "maybe" if unsure else "yes"
    if not unsure and (LEAD_SHORT.search(t) or DRAW_DIRECT.search(t)):
        return "yes"
    if AFTER.search(t) and POLITE.search(t) and not unsure:  # "Kannst du ein Bild von einem Hund generieren?"
        return "yes"
    if draw or AFTER.search(t) or LEAD_NOUN.search(t) or (len(t) < 200 and HAS_NOUN.search(t) and REQUEST.search(t)):
        return "maybe"
    return "no"


SYSTEM = ("You decide what a chat message wants. Answer with exactly one word: YES if the user asks you to create, draw, paint "
          "or generate a picture (an image, photo, illustration, logo, poster) right now; NO for everything else, such as "
          "questions about pictures, how to make pictures with a program, requests for code or text, or talking about an "
          "existing picture. The message may be in any language.")


def messages(text):
    """The chat model's task: is this message a request to make a picture?"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text[:MAX_LENGTH]}]


def parse(answer):
    """True when the chat model's answer says YES (or JA)."""
    return bool(re.match(r"^\W*(?:yes|ja|oui|sí|si|true|1)\b", (answer or "").strip(), F))


_SUBJECT = re.compile(rf"\b{NOUN}\s*(?:(?:von|vom|mit|of|showing|with)\b)?\s*[:,\-–]?\s+([\s\S]{{3,}})$", F)
_TAIL = re.compile(r"[\s,.!?]*\b(?:generier\w*|erzeug\w*|erstell\w*|mal\w*|zeichn\w*|generate|create|make|draw|paint|bitte|please)[\s.!?]*$", F)
_HEAD = re.compile(r"^\W*(?:(?:bitte|please|kannst du(?: mir)?|can you)\s+)?(?:mal(?:e|st)?|zeichn\w*|skizzier\w*|draw|paint|sketch)\s+(?:mir\s+|me\s+)?", F)


def subject(text):
    """The description without the request ("a lighthouse at dusk"); the whole text when none can be told apart."""
    t = text.strip()
    m = _SUBJECT.search(t)
    out = (m.group(1) if m else _HEAD.sub("", t)).strip()
    for _ in range(2):
        out = _TAIL.sub("", out)
    return out.strip() or t


# ---- chat requests to prepare a calendar event or an e-mail ("trag mir morgen 10 Uhr Zahnarzt ein", "schreib Anna eine Mail") ----
# Rules only, so that it works with every model. Only a command or a polite request counts: a question ("Was steht morgen an?",
# "Wie erstelle ich einen Termin in Outlook?"), a report ("Ich habe eine Mail geschrieben") or technical talk is a normal chat.
# Two steps. 1: an intent (a verb such as "write … e-mail" / "trag … ein", or a head such as "Termin am Freitag") with, for events,
# a concrete date or time. 2: exclusions that look only at the direct object: the words between the verb and "Mail"/"Termin" and
# the word right after it ("Mail-Vorlage", "meeting summary", "event loop"), never at the rest of the sentence.
_LEAD = (r"^\W*(?:(?:hey|hi|hallo|hello)\W+)?(?:sunak\W+)?(?:(?:bitte|please|kannst du(?: mir)?|könntest du(?: mir)?|kannst du|"
         r"can you(?: please)?|could you(?: please)?|would you(?: please)?|will you|ich (?:möchte|will|brauche|hätte gern|würde gern)(?: dass du)?|"
         r"i (?:want|need|would like|d like)(?: you)? to)\s+)*")
_LEAD_RE = re.compile(_LEAD, F)
_MAILN = r"(?:e-?mails?|mails?)(?![-\w])"
_MAIL_VERB = (r"(?:schreib\w*|verfass\w*|entwirf\w*|entwerf\w*|formulier\w*|sende\w*|schick\w*|bereite?\w*|write|draft|compose|send|"
              r"prepare|shoot|fire off)")
_MAIL_VERB_LATE = r"(?:schreib|verfass|formulier|entwerf|send|schick|verschick)\w*"
# words between the verb and the noun that show the noun is not the thing to make ("eine Zusammenfassung dieser Mail", "a plan for the meeting")
_BEFORE_NOT = re.compile(r"^(?:über|about|of|regarding|von|dieser|dieses|diese|diesen|this|that|these|newsletter|rundmail|spam|werbe\w*|marketing|"
                         r"zusammenfassung|summary|text|bericht|report|plan|präsentation|presentation|liste|list|agenda|notes?|protokoll|code|entwurf|draft)$", F)
# a word right after the noun that makes it part of a compound ("mail list", "meeting summary", "event loop")
_AFTER_NOT = re.compile(r"^\s+(?:list\w*|template\w*|vorlage\w*|adress\w*|address\w*|server|konto|account|zusammenfassung|summary|text\w*|client|"
                        r"programm|ordner|folder|signature|signatur|loop|agenda|notes?|minutes|protokoll|handler|listener|room|invite\w*|"
                        r"einladung\w*|plan|planner|link|series)\b", F)
_TIME = re.compile(
    r"\b(?:heute|morgen|übermorgen|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|today|tomorrow|tonight|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday|nächste\w*|kommende\w*|next|this\s+(?:week|evening|morning|afternoon)|\d{1,2}[:.]\d{2}|"
    r"\d{1,2}\s?(?:uhr|am|pm|h)|um\s+\d|at\s+\d|(?:am|on)\s+\d|\d{1,2}\.\d{1,2}\.|\d{4}-\d\d-\d\d|"
    r"in\s+(?:\d+|einer|einem|zwei|drei)\s+(?:tag\w*|woche\w*|stunde\w*|minute\w*|monat\w*|days?|weeks?|hours?|minutes?|months?))(?!\w)", F)
_EVENT_NOUN = (r"(?:termin(?:e|en)?|kalendereintr(?:ag|äge)|erinnerung(?:en)?|appointments?|events?|meetings?|reminders?|calendar\s+(?:entry|event))"
               r"(?![-\w])")
_EVENT_VERB = (r"(?:erstell\w*|leg\w*|mach\w*|plan\w*|erfass\w*|erzeug\w*|anleg\w*|create|make|add|arrange|"
               r"vereinbar\w*|buch\w*|schedule|book|set\s+up)")
_QUESTION_ACTION = re.compile(r"^\W*(?:(?:bitte|please)\s+)?(?:soll|sollte|sollen|muss|kann|darf|ist|sind|hat|habe|haben|has|have|did|do|does|is|are|should|"
                              r"(?:will|would|could|can)(?!\s+you\b))\b", F)
_TECH_ACTION = re.compile(r"\b(?:skript\w*|script\w*|code|python|funktion\w*|function\w*|programm\w*|api|javascript|html|css|docker|"
                          r"bibliothek\w*|library|befehl\w*|command\w*|regex|sql|smtp|imap|caldav|ical|plugin)\b", F)
_WH = re.compile(r"\b(?:what|how|why|whether|if|which|wie|was|warum|wieso|ob|welche\w*)\b", F)
_ASKING_TAIL = re.compile(r"[,;(\-–]\s*(?:any|some|irgendwelche|gibt es|do you have|hast du)?\s*(?:tips?|tipps?|advice|ratschl\w*|hints?|ideas?|ideen|suggestions?)\W*$", F)
_WEEKDAY = r"(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_EVENT_HEAD = re.compile(rf"^(?:(?:neuer|neue|new)\s+)?(?:termin|appointment|meeting)\b\s*(?::|(?=\s+(?:am|um|morgen|heute|übermorgen|{_WEEKDAY}|nächste\w*|"
                         r"kommende\w*|\d|with|mit|on|at|tomorrow|today|tonight|next)\b))", F)
_CALENDAR_PLACE = (r"(?:trag\w*|schreib\w*|setz\w*|pack\w*|schieb\w*|speicher\w*|füg\w*|leg\w*|add|put|save|enter|block|log|pencil)\b"
                   r"[^?!\n]{0,100}?\b(?:in|im|auf|zu|to|into|on)\s+(?:de[nm]|mein\w*|unser\w*|my|the|our)\s+(?:\w+\s+)?"
                   r"(?:kalender|terminkalender|planer|calendar|schedule|agenda)\b")


def _object_ok(between, after):
    """Step 2: the words before the noun and the one after it do not turn it into something else."""
    return not any(_BEFORE_NOT.match(w.strip(",.:;")) for w in between.split()) and not _AFTER_NOT.match(after)


def _mail(body, lead):
    if _ASKING_TAIL.search(body):
        return False
    m = re.match(rf"{_MAIL_VERB}\s+((?:\S+\s+){{0,4}}?){_MAILN}(.*)$", body, F | re.S)
    if m and _object_ok(m.group(1), m.group(2)):
        return True
    if re.match(r"(?:bitte\s+)?(?:kannst|könntest)\b", lead.strip(), F):  # "Kannst du eine Mail an Anna verfassen?"
        m = re.match(rf"((?:\S+\s+){{0,3}}?){_MAILN}((?:\s+(?:an|to|für)\s+[\w@.\-]+(?:\s+[\w@.\-]+){{0,2}})?\s*,?\s+{_MAIL_VERB_LATE})", body, F | re.S)
        if m and _object_ok(m.group(1), ""):
            return True
    return bool(re.match(rf"{_MAILN}\s+(?:an|to)\s+\w+", body, F) or re.match(r"e-?mail\s+\w+\s+(?:that|dass|and|und|about|wegen|to)\b", body, F))


def _event(t, body, lead):
    if re.match(rf"{_CALENDAR_PLACE}", body, F):  # names the calendar: no date needed, the model reads what there is
        return True
    if re.match(r"(?:bitte\s+)?(?:kannst|könntest) du(?: mir)?\b", lead.strip(), F) and re.search(r"\beintrag\w*", body, F):
        return True
    if not _TIME.search(t):
        return False
    if re.match(r"trag\w*\b[^?!\n]{0,100}?\bein\b[\s.!]*$", body, F) or (re.search(r"\beintragen\W*$", body, F) and not FIRST_PERSON.search(t)):
        return True
    if re.match(r"(?:erinner\w*\s+(?:mich|uns)|remind\s+(?:me|us))\b", body, F):
        return not _WH.search(body)  # "Remind me what we discussed" is a question about the past, not a reminder
    if re.match(r"schedule\s+(?:me\s+|us\s+)?(?:an?|my|the|our)\b", body, F) or _EVENT_HEAD.match(body):
        return True
    m = re.match(rf"{_EVENT_VERB}\s+((?:\S+\s+){{0,5}}?){_EVENT_NOUN}(.*)$", body, F | re.S)
    return bool(m and _object_ok(m.group(1), m.group(2)))


def action(text):
    """"event" (prepare a calendar event), "mail" (prepare an e-mail) or "" for a chat message."""
    t = (text or "").strip()
    if not t or len(t) > MAX_LENGTH or QUESTION.search(t) or _QUESTION_ACTION.search(t) or _TECH_ACTION.search(t):
        return ""
    if t.endswith("?") and not POLITE.search(t):
        return ""
    if classify(t) == "yes":  # "Erstelle ein Bild von einem Meeting" is a picture
        return ""
    lead = _LEAD_RE.match(t).group(0)
    body = t[len(lead):]
    if _mail(body, lead):
        return "mail"
    return "event" if _event(t, body, lead) else ""


def addresses(text):
    """The e-mail addresses in a text, in order, without duplicates."""
    return list(dict.fromkeys(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")))
