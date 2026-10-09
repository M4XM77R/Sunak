"""The language the model answers in: the interface language, which the page sends with every request."""

NAMES = {"en": "English", "de": "German"}


def clean(lang):
    """A known interface language code ("de", "en"), else ''."""
    return lang if isinstance(lang, str) and lang in NAMES else ""


def note(lang):
    """System-prompt sentence that makes the model answer in the interface language ('' for an unknown one).
    The user can still ask for another language in a message; translations, code and quotes are not affected."""
    lang = clean(lang)
    if not lang:
        return ""
    return (f"Answer in {NAMES[lang]}, the language of the user's interface, even if the user's message or attached text "
            f"is in another language. If the user explicitly asks for another language, use that one. "
            f"Translations, code and quotations stay in their own language.")
