"""The currencies Vicky handles: CAD, the default reporting currency, plus every currency the Bank
of Canada publishes a daily rate for (the conversion source, see `vicky.model.fx`).

Codes are lowercase ISO 4217, as figure units. Symbols are only used for display; the dollar
prefixes (US$, A$, NZ$) are the ones the audit already reads as money.
"""

import re

DEFAULT_CURRENCY = "cad"

# code → (name, display prefix)
CURRENCIES: dict[str, tuple[str, str]] = {
    "cad": ("Canadian dollar", "$"),
    "usd": ("US dollar", "US$"),
    "eur": ("Euro", "€"),
    "gbp": ("UK pound sterling", "£"),
    "aud": ("Australian dollar", "A$"),
    "nzd": ("New Zealand dollar", "NZ$"),
    "jpy": ("Japanese yen", "¥"),
    "cny": ("Chinese renminbi", "CN¥"),
    "hkd": ("Hong Kong dollar", "HK$"),
    "sgd": ("Singapore dollar", "S$"),
    "twd": ("New Taiwan dollar", "NT$"),
    "krw": ("South Korean won", "₩"),
    "inr": ("Indian rupee", "₹"),
    "idr": ("Indonesian rupiah", "Rp "),
    "myr": ("Malaysian ringgit", "RM "),
    "thb": ("Thai baht", "฿"),
    "chf": ("Swiss franc", "CHF "),
    "nok": ("Norwegian krone", "NOK "),
    "sek": ("Swedish krona", "SEK "),
    "pln": ("Polish zloty", "zł "),
    "try": ("Turkish lira", "₺"),
    "zar": ("South African rand", "R "),
    "mxn": ("Mexican peso", "MX$"),
    "brl": ("Brazilian real", "R$"),
    "pen": ("Peruvian new sol", "S/ "),
}

CURRENCY_CODES = frozenset(CURRENCIES)


def norm_currency(code: object, default: str = DEFAULT_CURRENCY) -> str:
    """A known lowercase code, else `default`."""
    c = str(code or "").strip().lower()
    return c if c in CURRENCIES else default


def symbol(code: str) -> str:
    return CURRENCIES.get(code, ("", code.upper() + " "))[1]


# Markers that name one currency without doubt. A bare "$" does not: it reads as the reporting currency.
_PREFIXES = {
    "us$": "usd",
    "u$s": "usd",
    "c$": "cad",
    "ca$": "cad",
    "cad$": "cad",
    "a$": "aud",
    "au$": "aud",
    "nz$": "nzd",
    "hk$": "hkd",
    "s$": "sgd",
    "sg$": "sgd",
    "nt$": "twd",
    "mx$": "mxn",
    "r$": "brl",
    "cn¥": "cny",
    "rmb": "cny",
}
_SYMBOLS = {"£": "gbp", "€": "eur", "¥": "jpy", "₹": "inr", "₩": "krw", "฿": "thb", "₺": "try", "zł": "pln"}
_WORDS = {"try", "pen"}  # also English words: only read as codes in capitals (TRY, PEN)
_CODES = "|".join(sorted(CURRENCIES, key=len, reverse=True))
_PLAIN_CODES = "|".join(sorted(set(CURRENCIES) - _WORDS))
_PREFIX_RX = "|".join(re.escape(p) for p in sorted(_PREFIXES, key=len, reverse=True))
_SYMBOL_RX = "|".join(re.escape(s) for s in _SYMBOLS)
MARKER_RE = re.compile(rf"(?<![a-z])({_PREFIX_RX})|({_SYMBOL_RX})|(?<![a-z])({_PLAIN_CODES})(?![a-z])", re.I)
WORD_CODE_RE = re.compile(r"(?<![A-Za-z])(TRY|PEN)(?![A-Za-z])")
# What a number cell may carry around it: a marker or a bare "$" (stripped before parsing).
STRIP_RE = re.compile(
    rf"^\s*(?:(?:{_PREFIX_RX})|(?:{_SYMBOL_RX})|(?:{_CODES})(?![a-z])|\$)\s*|"
    rf"\s*(?:(?:{_SYMBOL_RX})|(?<![a-z])(?:{_CODES})|\$)\s*$",
    re.I,
)


def currency_in(text: object) -> str | None:
    """The one currency a header or cell names (US$, £, "USD", "(EUR)" …), else None."""
    s = str(text or "").replace("_", " ")
    found = {m.group(1).lower() for m in WORD_CODE_RE.finditer(s)}
    for m in MARKER_RE.finditer(s.lower()):
        pre, sym, code = m.groups()
        found.add(_PREFIXES[pre] if pre else _SYMBOLS[sym] if sym else code)
    return found.pop() if len(found) == 1 else None


def strip_currency(text: str) -> str:
    """A header without its currency markers ("Revenue (USD)" → "Revenue ( )")."""
    s = WORD_CODE_RE.sub(" ", str(text or ""))
    return MARKER_RE.sub(" ", s)
