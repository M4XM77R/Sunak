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
_LEAD = (r"^\W*(?:(?:hey|hi|hallo|hello)\W+)?(?:sunak\W+)?(?:(?:bitte|please|kannst du(?: mir)?|könntest du(?: mir)?|kannst du|"
         r"can you(?: please)?|could you(?: please)?|would you(?: please)?|will you|ich (?:möchte|will|brauche|hätte gern|würde gern)(?: dass du)?|"
         r"i (?:want|need|would like|d like)(?: you)? to)\s+)*")
_MAILN = r"(?:e-?mails?|mails?)"
_MAIL_VERB = (r"(?:schreib\w*|verfass\w*|entwirf\w*|entwerf\w*|formulier\w*|sende\w*|schick\w*|bereite?\w*|write|draft|compose|send|"
              r"prepare|shoot|fire off)")
_ACTIONS = {
    "mail": [re.compile(p, F) for p in (
        rf"{_LEAD}{_MAIL_VERB}\b[^.?!\n]{{0,60}}?\b{_MAILN}\b",
        rf"{_LEAD}{_MAILN}\s+(?:an|to)\s+\w+",
        rf"{_LEAD}e-?mail\s+\w+\s+(?:that|dass|and|und|about|wegen|to)\b",
        rf"^\W*(?:bitte\s+)?(?:kannst|könntest) du(?: mir)?\b[^.?!\n]{{0,60}}?\b{_MAILN}\b[^.?!\n]{{0,80}}?\b(?:schreib|verfass|formulier|entwerf|send|schick|verschick)\w*",
    )],
    "event": [re.compile(p, F) for p in (
        rf"{_LEAD}(?:trag\w*|schreib\w*|setz\w*|pack\w*|schieb\w*|speicher\w*|füg\w*|leg\w*|add|put|save|enter|block|log|pencil)\b"
        r"[^.?!\n]{0,100}?\b(?:in|im|auf|zu|to|into|on)\s+(?:de[nm]|mein\w*|unser\w*|my|the|our)\s+(?:\w+\s+)?(?:kalender|terminkalender|planer|calendar|schedule|agenda)\b",
        rf"{_LEAD}trag\w*\b[^.?!\n]{{0,100}}?\bein\b[\s.!]*$",
        rf"^\W*(?:bitte\s+)?(?:kannst|könntest) du(?: mir)?\b[^.?!\n]{{0,100}}?\beintrag\w*",
        rf"{_LEAD}(?:erstell\w*|leg\w*|mach\w*|vereinbar\w*|buch\w*|plan\w*|erfass\w*|erzeug\w*|anleg\w*|schedule|book|create|make|set up|add|arrange)\b"
        r"[^.?!\n]{0,40}?\b(?:termin\w*|kalendereintr\w*|erinnerung\w*|appointments?|events?|meetings?|reminders?|calendar (?:entry|event))\b",
        rf"{_LEAD}erinner\w*\s+(?:mich|uns)\b",
        rf"{_LEAD}remind\s+(?:me|us)\b",
        rf"{_LEAD}schedule\s+(?:me\s+|us\s+)?(?:an?|my|the|our)\b",
    )],
}
_QUESTION_ACTION = re.compile(r"^\W*(?:(?:bitte|please)\s+)?(?:soll|sollte|sollen|muss|kann|darf|ist|sind|hat|habe|haben|has|have|did|do|does|is|are|should|"
                              r"will|would|could)\b", F)
_TECH_ACTION = re.compile(r"\b(?:skript\w*|script\w*|code|python|funktion\w*|function\w*|programm\w*|api|javascript|html|css|docker|"
                          r"bibliothek\w*|library|befehl\w*|command\w*|regex|sql|smtp|imap|caldav|ical|plugin)\b", F)


def action(text):
    """"event" (prepare a calendar event), "mail" (prepare an e-mail) or "" for a chat message."""
    t = (text or "").strip()
    if not t or len(t) > MAX_LENGTH or QUESTION.search(t) or _QUESTION_ACTION.search(t) or _TECH_ACTION.search(t):
        return ""
    if t.endswith("?") and not POLITE.search(t):
        return ""
    for kind in ("mail", "event"):
        if any(p.search(t) for p in _ACTIONS[kind]):
            return kind
    return ""


def addresses(text):
    """The e-mail addresses in a text, in order, without duplicates."""
    return list(dict.fromkeys(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")))
