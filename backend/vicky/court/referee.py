"""Pure-code turn referee: who may speak next, ranked.

score = bid × lane_fit × fairness_decay(turns since the VC last spoke)
- follow-ups get a bonus when the last answer was weak, but stop at the depth cap (≤ 3);
- a jump-in must beat the best non-jump-in candidate by `JUMP_MARGIN`;
- a VC that just spoke is cooled down unless it is following up.
The chair (Vicky) picks from this list; any invalid or late pick falls back to `ranked[0]`. Vicky may
put a `knowledge` candidate at the top when a knowledge check is due (`vicky.court.knowledge.candidate`).
"""

from dataclasses import dataclass, field
from typing import Literal

Intent = Literal["follow_up", "new_topic", "jump_in", "pass", "knowledge"]
DEPTH_CAP = 3
JUMP_MARGIN = 0.2
FOLLOW_UP_BONUS = 0.25
COOLDOWN_TURNS = 1


@dataclass
class Bid:
    vc_id: str
    bid: float
    intent: Intent
    target_hyp: str | None
    lane_fit: float = 1.0  # persona weight on the target hypothesis's lens
    turns_since_spoke: int = 99
    is_current: bool = False  # owns the thread being followed up
    depth: int = 0  # follow-ups already asked on the current thread
    max_depth: int = DEPTH_CAP


@dataclass
class Candidate:
    vc_id: str
    intent: Intent
    target_hyp: str | None
    score: float
    reasons: list[str] = field(default_factory=list)


def fairness_decay(turns_since_spoke: int) -> float:
    if turns_since_spoke <= 0:
        return 0.5
    return min(1.0, 0.55 + 0.15 * turns_since_spoke)


def rank(bids: list[Bid], answer_weak: bool) -> list[Candidate]:
    out: list[Candidate] = []
    for b in bids:
        if b.intent == "pass" or b.bid <= 0:
            continue
        reasons = []
        intent = b.intent
        if intent == "follow_up":
            cap = min(DEPTH_CAP, b.max_depth)
            if not b.is_current or b.depth >= cap:
                intent = "new_topic"
                reasons.append(f"depth cap {cap} reached" if b.is_current else "not the thread owner")
        score = b.bid * max(0.05, b.lane_fit)
        if intent == "follow_up":
            if answer_weak:
                score += FOLLOW_UP_BONUS
                reasons.append("follow-up bonus: weak answer")
        else:
            if b.turns_since_spoke < COOLDOWN_TURNS + 1 and not b.is_current:
                score *= 0.6
                reasons.append("cooldown")
            score *= fairness_decay(b.turns_since_spoke)
            if b.is_current:
                score *= 0.7
                reasons.append("just asked; others first")
        out.append(Candidate(b.vc_id, intent, b.target_hyp, round(score, 4), reasons))
    out.sort(key=lambda c: -c.score)
    # A jump-in only wins with a clear margin over the best ordinary candidate.
    if out and out[0].intent == "jump_in":
        best_other = next((c for c in out[1:] if c.intent != "jump_in"), None)
        if best_other and out[0].score - best_other.score < JUMP_MARGIN:
            out.remove(best_other)
            out.insert(0, best_other)
            best_other.reasons.append("jump-in margin not met")
    return out


def validate(decision: dict, ranked: list[Candidate]) -> tuple[bool, str]:
    """A chair decision is valid only if it names a ranked candidate (so cooldowns and caps hold)."""
    if decision.get("action") == "end_session":
        return True, "end"
    vc = decision.get("vc_id")
    cand = pick(decision, ranked)
    if cand is None:
        if decision.get("intent") == "knowledge" and any(c.vc_id == vc for c in ranked):
            return False, "no knowledge check is due for that investor"
        return False, f"{vc!r} is not an eligible speaker"
    if decision.get("intent") == "follow_up" and cand.intent != "follow_up":
        return False, "follow-up not allowed (depth cap or not the thread owner)"
    return True, "ok"


def pick(decision: dict, ranked: list[Candidate]) -> Candidate | None:
    """The candidate a chair decision names: a knowledge check only when one is on offer for that
    investor, otherwise the investor's ordinary candidate."""
    vc, want_k = decision.get("vc_id"), decision.get("intent") == "knowledge"
    return next((c for c in ranked if c.vc_id == vc and (c.intent == "knowledge") == want_k), None)
