# urdu_devanagari.py - Urdu (Nastaliq) to Devanagari, so Hindi readers and speech models can read it
#
# Spoken Urdu and Hindi share their sounds, so Urdu written in Devanagari reads aloud as Urdu.
# indic-transliteration's "urdu" scheme leaves most Urdu letters unconverted, so this module maps
# the text itself. Urdu normally omits short vowels; letters without one keep Devanagari's
# inherent "a", which Hindi readers (and XTTS-v2) shorten the way they would in Hindi words.
# The letters و, ی, and ہ act as consonants or vowels depending on position, and the most common
# words, whose spelling doesn't follow the letters, are looked up whole.

import re

_WORDS: dict[str, str] = {
    # Forms of "to be" and auxiliaries
    "ہے": "है", "ہیں": "हैं", "ہو": "हो", "ہوں": "हूँ", "ہوا": "हुआ", "ہوئی": "हुई", "ہوئے": "हुए",
    "تھا": "था", "تھی": "थी", "تھے": "थे", "ہوگا": "होगा", "ہوگی": "होगी", "ہوں گے": "होंगे",
    "ہونا": "होना", "ہوتا": "होता", "ہوتی": "होती", "ہوتے": "होते", "رہا": "रहा", "رہی": "रही",
    "رہے": "रहे", "گیا": "गया", "گئی": "गई", "گئے": "गए", "سکتا": "सकता", "سکتی": "सकती",
    "سکتے": "सकते", "چاہیے": "चाहिए", "چاہئے": "चाहिए", "جائے": "जाए", "جائیں": "जाएँ",
    "کر": "कर", "کرو": "करो", "کریں": "करें", "کرنا": "करना", "کرنے": "करने", "کرتا": "करता",
    "کرتی": "करती", "کرتے": "करते", "کیا": "क्या", "کیے": "किए", "کئے": "किए", "دیا": "दिया",
    "دی": "दी", "دیے": "दिए", "دیں": "दें", "لیا": "लिया", "لی": "ली", "لیے": "लिए", "لئے": "लिए",
    # Pronouns and determiners
    "میں": "में", "مَیں": "मैं", "ہم": "हम", "تم": "तुम", "آپ": "आप", "یہ": "ये", "وہ": "वो",
    "اس": "इस", "ان": "इन", "اسے": "इसे", "انہیں": "उन्हें", "انہوں": "उन्हों", "اُن": "उन",
    "اُس": "उस", "میرا": "मेरा", "میری": "मेरी", "میرے": "मेरे", "تیرا": "तेरा", "تیری": "तेरी",
    "تیرے": "तेरे", "تمہارا": "तुम्हारा", "تمہاری": "तुम्हारी", "تمہارے": "तुम्हारे",
    "ہمارا": "हमारा", "ہماری": "हमारी", "ہمارے": "हमारे", "اپنا": "अपना", "اپنی": "अपनी",
    "اپنے": "अपने", "کچھ": "कुछ", "سب": "सब", "ہر": "हर", "کوئی": "कोई", "کسی": "किसी",
    "جو": "जो", "جس": "जिस", "جن": "जिन", "کون": "कौन", "کیوں": "क्यों", "کیسے": "कैसे",
    "کیسا": "कैसा", "کیسی": "कैसी", "کہاں": "कहाँ", "یہاں": "यहाँ", "وہاں": "वहाँ",
    # Particles, postpositions, and conjunctions
    "کو": "को", "سے": "से", "کا": "का", "کی": "की", "کے": "के", "پر": "पर", "نے": "ने",
    "بھی": "भी", "ہی": "ही", "تو": "तो", "اور": "और", "یا": "या", "لیکن": "लेकिन", "مگر": "मगर",
    "اگر": "अगर", "کہ": "कि", "نہیں": "नहीं", "نہ": "न", "ہاں": "हाँ", "جی": "जी", "اب": "अब",
    "جب": "जब", "تب": "तब", "بہت": "बहुत", "زیادہ": "ज़्यादा", "کم": "कम", "پہلے": "पहले",
    "بعد": "बाद", "ساتھ": "साथ", "بارے": "बारे", "طرح": "तरह", "یعنی": "यानी", "بالکل": "बिल्कुल",
    # Numbers and frequent words
    "ایک": "एक", "دو": "दो", "تین": "तीन", "چار": "चार", "پانچ": "पाँच", "شکریہ": "शुक्रिया",
    "خوش": "ख़ुश", "آمدید": "आमदीद", "سلام": "सलाम", "ہیلو": "हेलो", "نیا": "नया", "نئی": "नई",
    "نئے": "नए", "وقت": "वक़्त", "لوگ": "लोग", "بات": "बात", "کام": "काम", "دیکھ": "देख",
    "دیکھیں": "देखें", "سمجھ": "समझ", "مکمل": "मुकम्मल", "ضرور": "ज़रूर", "کورس": "कोर्स",
    "مجھے": "मुझे", "مجھ": "मुझ", "تجھے": "तुझे", "ہمیں": "हमें", "تمہیں": "तुम्हें", "کہا": "कहा",
    "کہیں": "कहीं", "یہیں": "यहीं", "وہیں": "वहीं", "کبھی": "कभी", "ابھی": "अभी", "سبھی": "सभी",
    "تاکہ": "ताकि", "امید": "उम्मीद", "صرف": "सिर्फ़", "پھر": "फिर", "دوبارہ": "दोबारा",
}
# Urdu writes the future ending as its own word; Hindi joins it to the verb (کریں گے -> करेंगे).
_FUTURE_ENDINGS = {"گا", "گی", "گے"}

_CONSONANTS: dict[str, str] = {
    "ب": "ब", "پ": "प", "ت": "त", "ٹ": "ट", "ث": "स", "ج": "ज", "چ": "च", "ح": "ह", "خ": "ख़",
    "د": "द", "ڈ": "ड", "ذ": "ज़", "ر": "र", "ڑ": "ड़", "ز": "ज़", "ژ": "झ़", "س": "स", "ش": "श",
    "ص": "स", "ض": "ज़", "ط": "त", "ظ": "ज़", "غ": "ग़", "ف": "फ़", "ق": "क़", "ک": "क", "گ": "ग",
    "ل": "ल", "م": "म", "ن": "न", "ۃ": "त",
}
# A consonant followed by ھ (do-chashmi he) is aspirated: کھ -> ख.
_ASPIRATED: dict[str, str] = {
    "ک": "ख", "گ": "घ", "چ": "छ", "ج": "झ", "ٹ": "ठ", "ڈ": "ढ", "ت": "थ", "د": "ध", "پ": "फ",
    "ب": "भ", "ڑ": "ढ़",
}
_ZABAR, _ZER, _PESH, _SHADDA, _TANWEEN = "َ", "ِ", "ُ", "ّ", "ً"
# Sukun, hamza marks, tatweel, zero-width joiners, and superscript alif carry no sound of their own.
_IGNORED = {"ْ", "ٔ", "ٕ", "ـ", "‌", "‍", "ٰ"}
_PUNCTUATION: dict[str, str] = {"۔": "।", "،": ",", "؟": "?", "؛": ";", "«": '"', "»": '"'}
_DIGITS = {chr(0x06F0 + d): str(d) for d in range(10)} | {chr(0x0660 + d): str(d) for d in range(10)}
# Variant code points Arabic keyboards and translators produce for the same Urdu letters.
_NORMALIZE = str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "ە": "ہ", "ة": "ہ", "ۓ": "ئے", "ۂ": "ہ"})

_TOKEN_RE = re.compile(r"[؀-ۿݐ-ݿ‌‍]+|[^؀-ۿݐ-ݿ‌‍]+")


def urdu_to_devanagari(text: str) -> str:
    """Write Urdu text in Devanagari; anything that isn't Urdu (Latin, digits) passes through."""
    text = text.translate(_NORMALIZE)
    words = text.split(" ")
    # Two-word entries ("ہوں گے") are checked before single words.
    out: list[str] = []
    i = 0
    while i < len(words):
        pair = f"{words[i]} {words[i + 1]}" if i + 1 < len(words) else ""
        if pair in _WORDS:
            out.append(_WORDS[pair])
            i += 2
            continue
        converted = "".join(_convert_run(run) for run in _TOKEN_RE.findall(words[i]))
        if words[i].rstrip("۔،؟.,?!") in _FUTURE_ENDINGS and out and out[-1]:
            out[-1] += converted
        else:
            out.append(converted)
        i += 1
    return " ".join(out)


def _convert_run(run: str) -> str:
    """Convert one run of Urdu letters (or pass a non-Urdu run through, mapping punctuation)."""
    if not ("؀" <= run[0] <= "ۿ" or "ݐ" <= run[0] <= "ݿ" or run[0] in "‌‍"):
        return run
    core = "".join(ch for ch in run if ch not in _PUNCTUATION and ch not in _DIGITS and ch not in "‌‍")
    if core and core in _WORDS:
        word = _WORDS[core]
    else:
        word = _convert_word(core) if core else ""
    # Punctuation and digits keep their place around the word.
    lead = ""
    for ch in run:
        if ch in _PUNCTUATION or ch in _DIGITS:
            lead += _PUNCTUATION.get(ch) or _DIGITS[ch]
        else:
            break
    trail = ""
    for ch in reversed(run):
        if ch in _PUNCTUATION or ch in _DIGITS:
            trail = (_PUNCTUATION.get(ch) or _DIGITS[ch]) + trail
        else:
            break
    if not core:
        return lead
    return lead + word + trail


def _convert_word(word: str) -> str:
    """Letter-by-letter conversion of one Urdu word with no dictionary entry."""
    letters = [ch for ch in word if ch not in _IGNORED]
    out: list[str] = []
    # What the last emitted sound was: "start", "consonant", or "vowel".
    prev = "start"
    i = 0
    n = len(letters)
    while i < n:
        ch = letters[i]
        nxt = letters[i + 1] if i + 1 < n else ""
        last = i == n - 1
        if ch in _CONSONANTS:
            if nxt == "ھ":
                out.append(_ASPIRATED.get(ch, _CONSONANTS[ch] + "्ह"))
                i += 1
            else:
                out.append(_CONSONANTS[ch])
            prev = "consonant"
        elif ch == "ھ":
            out.append("ह")
            prev = "consonant"
        elif ch == _ZABAR:
            pass  # the inherent vowel already says "a"
        elif ch == _ZER:
            out.append("ि" if prev == "consonant" else "इ")
            prev = "vowel"
        elif ch == _PESH:
            out.append("ु" if prev == "consonant" else "उ")
            prev = "vowel"
        elif ch == _SHADDA:
            if out and prev == "consonant":
                out.append("्" + out[-1])  # doubled consonant: محبت with shadda -> मुहब्बत
        elif ch == _TANWEEN:  # on a final alif: فوراً -> fauran
            out.append("न")
            prev = "consonant"
        elif ch == "آ":
            out.append("ा" if prev == "consonant" else "आ")
            prev = "vowel"
        elif ch == "ا":
            if prev == "start":
                if nxt in (_ZER, _PESH):  # اِس -> इस, اُن -> उन
                    out.append("इ" if nxt == _ZER else "उ")
                    i += 1
                elif nxt == "ی":
                    out.append("ए")
                    i += 1
                elif nxt == "و":
                    out.append("औ")
                    i += 1
                else:
                    out.append("अ")
            elif prev == "consonant":
                out.append("ा")
            else:
                out.append("आ")
            prev = "vowel"
        elif ch == "و":
            if prev == "start" or (prev == "consonant" and nxt in ("ا", "آ")):
                out.append("व")
                prev = "consonant"
            else:
                out.append("ो" if prev == "consonant" else "ओ")
                prev = "vowel"
        elif ch == "ی":
            if prev == "start" or nxt in ("ا", "آ", "و"):
                out.append("य")
                prev = "consonant"
            elif prev == "consonant" and nxt == "ں" and i + 2 == n:
                # A final یں is a verb or plural ending: لیں -> लें, کتابیں -> किताबें.
                out.append("ें")
                prev = "vowel"
                i += 1
            else:
                out.append("ी" if prev == "consonant" else "ई")
                prev = "vowel"
        elif ch == "ے":
            out.append("े" if prev == "consonant" else "ए")
            prev = "vowel"
        elif ch == "ئ":
            if nxt == "ی" and i + 2 < n and letters[i + 2] == "ں":
                out.append("एँ")
                i += 2
            elif nxt == "ے":
                out.append("ए")
                i += 1
            elif nxt == "ی":
                out.append("ई")
                i += 1
            elif nxt == "و":
                out.append("ओ")
                i += 1
            else:
                out.append("इ")
            prev = "vowel"
        elif ch == "ؤ":
            out.append("ओ")
            prev = "vowel"
        elif ch == "ء":
            pass
        elif ch == "ہ":
            # A final he after a consonant is silent and stands for "a" (زندہ -> ज़िंदा).
            if last and prev == "consonant":
                out.append("ा")
                prev = "vowel"
            else:
                out.append("ह")
                prev = "consonant"
        elif ch == "ع":
            if prev == "start":
                out.append("आ" if nxt == "ا" else "अ")
                if nxt == "ا":
                    i += 1
                prev = "vowel"
            elif prev == "consonant" and not last:
                out.append("ा")
                prev = "vowel"
        elif ch == "ں":
            out.append("ं")
        else:
            out.append(ch)
        i += 1
    return "".join(out)
