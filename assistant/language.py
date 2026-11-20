"""Very small language guesser (uz / ru / en). It is only a hint for Claude."""
from __future__ import annotations

import re
from typing import Optional

APOSTROPHES = "'ʻ’‘`ʼ"

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_UZ_CYRILLIC_LETTERS_RE = re.compile(r"[ўқғҳЎҚҒҲ]")
_UZ_CYRILLIC_WORDS = (
    "салом", "ассалому", "рахмат", "раҳмат", "яхши", "нима", "қалесан", "калесан", "йўқ", "бугун",
    "эртага", "керак", "қаерда", "каерда", "хоп", "бопти", "ҳозир", "хозир", "кейин", "менга", "сизга",
)
_UZ_CYRILLIC_SUFFIXES = ("мисан", "мисиз", "мизми", "япсан", "япман", "япти", "ганман")

# o' / g' with any apostrophe, but not English "'s" (dog's, Leo's) or "o'clock".
_UZ_APOSTROPHE_RE = re.compile(rf"[og][{APOSTROPHES}](?!s\b)(?!clock)", re.IGNORECASE)
_UZ_LATIN_WORDS = frozenset(
    {
        "salom", "assalomu", "alaykum", "rahmat", "raxmat", "yaxshi", "nima", "nimaga", "qalesan", "qalaysan",
        "qayerda", "qayerdasan", "bugun", "ertaga", "kecha", "kerak", "xop", "bopti", "zor", "hozir", "keyin",
        "men", "sen", "siz", "yoq", "mayli", "qachon", "qanday", "nega", "opa", "ukam",
        "rahmet", "tushundim", "bilmadim", "boshmisan", "qilyapsan",
    }
)
_UZ_LATIN_SUFFIXES = ("misan", "misiz", "mizmi", "yapsan", "yapman", "yapti", "yapmiz", "asizmi", "ganman", "dingmi")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_language(text: str) -> Optional[str]:
    """Return "uz", "ru", "en", or None when the text has no letters."""
    if not text:
        return None
    cyr = len(_CYRILLIC_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    if cyr == 0 and lat == 0:
        return None

    if cyr > lat:
        if _UZ_CYRILLIC_LETTERS_RE.search(text):
            return "uz"
        words = _WORD_RE.findall(text.lower())
        for word in words:
            if any(word.startswith(w) for w in _UZ_CYRILLIC_WORDS) or word.endswith(_UZ_CYRILLIC_SUFFIXES):
                return "uz"
        return "ru"

    if _UZ_APOSTROPHE_RE.search(text):
        return "uz"
    stripped = text.lower()
    for ch in APOSTROPHES:
        stripped = stripped.replace(ch, "")
    for word in _WORD_RE.findall(stripped):
        if word in _UZ_LATIN_WORDS or word.endswith(_UZ_LATIN_SUFFIXES):
            return "uz"
    return "en"


LANGUAGE_NAMES = {"uz": "Uzbek", "ru": "Russian", "en": "English"}
