"""Okapi BM25 over the knowledge-base chunks, in process (docs/08-RAG.md §Retrieval).

The vault is one global set of a few thousand chunks, so an inverted index in a dict is a few MB and answers
in about a millisecond; no extension or extra service. Index and query go through the same `tokens()`
(lowercase, stopwords dropped, a light English stemmer), and query terms carry weights so glossary
expansions count at half weight.
"""

import math
import re
from array import array
from collections import Counter, defaultdict
from functools import lru_cache

K1 = 1.2
B = 0.75

STOPWORDS = frozenset(
    """a an and are as at be but by can could did do does for from had has have how i if in
into is it its me my of on or our so than that the their them then there these they this to us was we were
what when where which who why will with would you your about any all also just more most much no not only
other over per some such very re ll ve don isn aren won didn doesn wasn weren hasn haven""".split()
)

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@lru_cache(maxsize=200_000)  # a vault's vocabulary is small; tokenizing a large one is mostly repeat words
def stem(w: str) -> str:
    """A small, deterministic suffix stripper: plural, -ing, -ed, -ly, -ment, -ness, -ation forms, then a final
    "e" ("hire", "hired", "hiring" → "hir"). It only has to map a query word and a note word to the same key,
    not to a dictionary word."""
    base = _strip(w)
    return base[:-1] if len(base) > 3 and base.endswith("e") and not w.isdigit() else base


def _strip(w: str) -> str:
    if len(w) <= 3 or w.isdigit():
        return w
    for suf, rep in (
        ("ational", "ate"),
        ("ization", "ize"),
        ("ations", "ate"),
        ("ation", "ate"),
        ("nesses", ""),
        ("ness", ""),
        ("ments", ""),
        ("ment", ""),
        ("ingly", ""),
        ("edly", ""),
        ("ings", ""),
        ("ing", ""),
        ("ies", "y"),
        ("ied", "y"),
        ("ers", "er"),
        ("ly", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
    ):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            if suf == "s" and w.endswith(("ss", "us", "is")):
                return w
            if suf == "es" and not w.endswith(("ches", "shes", "sses", "xes", "zes")):
                return w[:-1]  # "rates" → "rate", but "taxes" → "tax"
            base = w[: len(w) - len(suf)] + rep
            if (
                suf in ("ing", "ed", "edly", "ingly", "ings")
                and len(base) > 3
                and base[-1] == base[-2]
                and base[-1] not in "lsz"
            ):
                base = base[:-1]  # "planned" → "plan"
            return base
    return w


def words(text: str) -> list[str]:
    return _WORD.findall((text or "").replace("’", "'").lower())


def tokens(text: str) -> list[str]:
    return [stem(w) for w in words(text) if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]


class BM25:
    """Postings are two compact arrays per term (doc ids, term frequencies): about 8 bytes a posting instead
    of a tuple's ~70, which keeps a large vault's index well inside a 512 MB instance."""

    def __init__(self, docs):
        self.lengths = array("I")
        docs_: dict[str, array] = defaultdict(lambda: array("I"))
        tfs: dict[str, array] = defaultdict(lambda: array("H"))
        for i, d in enumerate(docs):
            self.lengths.append(len(d))
            for t, tf in Counter(d).items():
                docs_[t].append(i)
                tfs[t].append(min(tf, 65535))
        self.n = len(self.lengths)
        self.avg = (sum(self.lengths) / self.n) if self.n else 0.0
        self.postings = {t: (docs_[t], tfs[t]) for t in docs_}
        self.idf = {
            t: math.log(1 + (self.n - len(p[0]) + 0.5) / (len(p[0]) + 0.5)) for t, p in self.postings.items()
        }

    def search(
        self, query: dict[str, float], top: int = 50, only: set[int] | None = None
    ) -> list[tuple[int, float]]:
        """`query` maps a token to its weight. Returns (doc index, score), best first."""
        scores: dict[int, float] = defaultdict(float)
        avg = self.avg or 1
        for t, w in query.items():
            idf = self.idf.get(t)
            if idf is None:
                continue
            ids, tfs = self.postings[t]
            for i, tf in zip(ids, tfs, strict=True):
                if only is not None and i not in only:
                    continue
                norm = K1 * (1 - B + B * self.lengths[i] / avg)
                scores[i] += w * idf * tf * (K1 + 1) / (tf + norm)
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
