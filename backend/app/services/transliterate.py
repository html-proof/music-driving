"""Indic script -> Latin transliteration for search, with no dependencies.

Gaana's search finds songs by their Latin (romanised) titles and handles native script
poorly, so a query such as "മലരേ" is also searched as "malare". This is a phonetic,
lossy romanisation tuned to how Indian song titles are usually written in Latin script
(long vowels collapse: "aa" -> "a"), not a scholarly transliteration.

The nine major Indic Unicode blocks (Devanagari, Bengali, Gurmukhi, Gujarati, Oriya,
Tamil, Telugu, Kannada, Malayalam) follow the ISCII layout: a letter's offset from the
start of its block names the same sound in every script. One table indexed by that
offset covers them all; a few per-script overrides handle what differs.
"""

import re
import unicodedata

_BLOCK_START = 0x0900
_BLOCK_SIZE = 0x80
# Block index -> script, in Unicode order.
_SCRIPTS = ("devanagari", "bengali", "gurmukhi", "gujarati", "oriya", "tamil", "telugu", "kannada", "malayalam")
# Northern scripts drop the inherent vowel at the end of a word ("तुम" is "tum").
_SCHWA_DELETION = {"devanagari", "bengali", "gurmukhi", "gujarati"}

_VIRAMA = 0x4D
_NUKTA = 0x3C

# Independent vowels.
_VOWELS = {
    0x04: "a", 0x05: "a", 0x06: "a", 0x07: "i", 0x08: "i", 0x09: "u", 0x0A: "u", 0x0B: "ri", 0x0C: "li",
    0x0D: "e", 0x0E: "e", 0x0F: "e", 0x10: "ai", 0x11: "o", 0x12: "o", 0x13: "o", 0x14: "au",
    0x60: "ri", 0x61: "li",
}
# Consonants (they carry an inherent "a" unless followed by a vowel sign or virama).
_CONSONANTS = {
    0x15: "k", 0x16: "kh", 0x17: "g", 0x18: "gh", 0x19: "ng",
    0x1A: "ch", 0x1B: "chh", 0x1C: "j", 0x1D: "jh", 0x1E: "ny",
    0x1F: "t", 0x20: "th", 0x21: "d", 0x22: "dh", 0x23: "n",
    0x24: "t", 0x25: "th", 0x26: "d", 0x27: "dh", 0x28: "n", 0x29: "n",
    0x2A: "p", 0x2B: "ph", 0x2C: "b", 0x2D: "bh", 0x2E: "m",
    0x2F: "y", 0x30: "r", 0x31: "r", 0x32: "l", 0x33: "l", 0x34: "zh", 0x35: "v",
    0x36: "sh", 0x37: "sh", 0x38: "s", 0x39: "h",
    # Nukta forms (Devanagari क़ ख़ ग़ ज़ ड़ ढ़ फ़ य़; same offsets in Gurmukhi, Bengali, Oriya).
    0x58: "k", 0x59: "kh", 0x5A: "g", 0x5B: "z", 0x5C: "r", 0x5D: "rh", 0x5E: "f", 0x5F: "y",
}
# Scripts whose offsets 0x58-0x5F are the nukta forms above (elsewhere they differ).
_NUKTA_FORMS = {"devanagari", "bengali", "gurmukhi", "oriya"}
# Dependent vowel signs (matras).
_SIGNS = {
    0x3E: "a", 0x3F: "i", 0x40: "i", 0x41: "u", 0x42: "u", 0x43: "ri", 0x44: "ri", 0x45: "e", 0x46: "e",
    0x47: "e", 0x48: "ai", 0x49: "o", 0x4A: "o", 0x4B: "o", 0x4C: "au", 0x62: "li", 0x63: "li",
}
# Signs that follow a syllable: candrabindu, anusvara, visarga.
_MODIFIERS = {0x01: "n", 0x02: "n", 0x03: "h"}

# Per-script differences: (offset -> romanisation) by role.
_CONSONANT_OVERRIDES = {
    "tamil": {0x1A: "ch", 0x31: "r", 0x33: "l", 0x34: "zh", 0x29: "n"},
    "bengali": {0x70: "r", 0x71: "w"},  # Assamese ra / wa
    "oriya": {0x71: "w"},
    "telugu": {0x58: "ts", 0x59: "dz", 0x5A: "r"},
    "kannada": {0x5E: "zh"},
}
# Malayalam chillus (U+0D7A-0D7F, U+0D54-0D56), Bengali khanda ta: final consonants
# without an inherent vowel.
_FINALS = {
    "malayalam": {0x7A: "n", 0x7B: "n", 0x7C: "r", 0x7D: "l", 0x7E: "l", 0x7F: "k", 0x54: "m", 0x55: "y",
                  0x56: "zh"},
    "bengali": {0x4E: "t"},
}
_MODIFIER_OVERRIDES = {
    "malayalam": {0x02: "m"},  # Malayalam anusvara is "m"
    "bengali": {0x02: "ng"},  # Bengali anusvara is "ng" ("বাংলা" is "bangla")
    "gurmukhi": {0x70: "n"},  # tippi
    "tamil": {0x03: "h"},  # aytham
}
# Gurmukhi addak doubles the next consonant.
_GEMINATE = {"gurmukhi": 0x71}

_SPACE = re.compile(r"\s+")


def _script(ch: str) -> tuple[str, int] | None:
    cp = ord(ch)
    index, offset = divmod(cp - _BLOCK_START, _BLOCK_SIZE)
    if cp < _BLOCK_START or index >= len(_SCRIPTS):
        return None
    return _SCRIPTS[index], offset


def has_indic(text: str) -> bool:
    return any(_script(ch) is not None and unicodedata.category(ch)[0] in "LM" for ch in text)


def transliterate(text: str) -> str | None:
    """Latin (lower-case ASCII) form of `text`, or None when it has no Indic letters.

    Non-Indic letters and digits are kept (lower-cased, accents removed); other
    characters become spaces."""
    if not text or not has_indic(text):
        return None
    # ZWJ/ZWNJ only shape glyphs (e.g. old-style Malayalam chillus "ന്‍"); they are not
    # word breaks, so drop them before romanising.
    chars = unicodedata.normalize("NFC", text).replace("‍", "").replace("‌", "")
    out: list[str] = []
    i, size = 0, len(chars)
    geminate = False
    while i < size:
        ch = chars[i]
        info = _script(ch)
        if info is None:
            out.append(_latin(ch))
            i += 1
            continue
        script, off = info
        if unicodedata.category(ch)[0] not in "LMN":  # fractions, signs, symbols
            out.append(" ")
            i += 1
            continue
        cons = _CONSONANT_OVERRIDES.get(script, {}).get(off)
        if cons is None and (off < 0x58 or script in _NUKTA_FORMS):
            cons = _CONSONANTS.get(off)
        if cons is not None:
            if geminate:
                out.append(cons[0])
                geminate = False
            out.append(cons)
            # Look past a nukta at what follows the consonant.
            j = i + 1
            while j < size and _offset_in(chars[j], script) == _NUKTA:
                j += 1
            nxt = _offset_in(chars[j], script) if j < size else None
            if nxt == _VIRAMA:
                j += 1  # dead consonant: no vowel
            elif nxt in _SIGNS:
                out.append(_SIGNS[nxt])
                j += 1
            elif not (script in _SCHWA_DELETION and _word_ends(chars, j)):
                out.append("a")
            i = j
            continue
        final = _FINALS.get(script, {}).get(off)
        if final is not None:
            out.append(final)
        elif off in _VOWELS:
            out.append(_VOWELS[off])
        elif off in _SIGNS:  # a vowel sign without a consonant: say the vowel
            out.append(_SIGNS[off])
        elif (mod := _MODIFIER_OVERRIDES.get(script, {}).get(off) or _MODIFIERS.get(off)) is not None:
            out.append(mod)
        elif _GEMINATE.get(script) == off:
            geminate = True
        elif 0x66 <= off <= 0x6F:  # digits
            out.append(str(off - 0x66))
        elif off in (0x64, 0x65):  # danda, double danda
            out.append(" ")
        # Anything else (nukta, virama on its own, avagraha, length marks) is silent.
        i += 1
    result = _SPACE.sub(" ", "".join(out)).strip()
    return result or None


def _offset_in(ch: str, script: str) -> int | None:
    info = _script(ch)
    return info[1] if info and info[0] == script else None


def _word_ends(chars: str, j: int) -> bool:
    """True when nothing at `j` continues the word (end, space, punctuation, other script)."""
    if j >= len(chars):
        return True
    info = _script(chars[j])
    if info is None:
        return not chars[j].isalnum()
    return False


def _latin(ch: str) -> str:
    if ch.isascii():
        return ch.lower() if ch.isalnum() else " "
    base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
    return base.lower() if base.isalnum() else " "
