"""Vik's review of an investor's drafted line, deterministic part.

Every line is drafted by the investor, audited for figures (`audit_text`), then reviewed by Vik before
it is spoken: one question, short, not a repeat of an earlier question, in the investor's lane, and,
for a knowledge check, not giving the answer away. Code issues always send a line back; on the LLM path
Vik can add issues of her own (`vik.llm.minds.review_line`).
"""

import re

MAX_WORDS = 70
REPEAT_JACCARD = 0.6
GIVEAWAY = 0.6


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z'-]{2,}", (s or "").lower()))


def jaccard(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def review(text: str, *, asked: list[str], intent: str, answer_key: str | None = None) -> dict:
    issues = []
    if len(text.split()) > MAX_WORDS:
        issues.append(f"too long: keep it under {MAX_WORDS} words")
    if "?" not in text:
        issues.append("it isn't a question")
    elif text.count("?") > 2:
        issues.append("ask one question, not several")
    if any(jaccard(text, q) >= REPEAT_JACCARD for q in asked):
        issues.append("it repeats an earlier question")
    if intent == "knowledge" and answer_key:
        key = _words(answer_key)
        if key and len(_words(text) & key) / len(key) >= GIVEAWAY:
            issues.append("it gives the answer away")
    return {
        "verdict": "revise" if issues else "approve",
        "issues": issues,
        "note": "; ".join(issues),
        "source": "code",
    }
