"""Snake-draft strategy: pick schedule, market awareness, opportunity cost.

Raw VORP answers "how good is this player." It does not answer the question you
actually face on the clock, which is:

    Of the players I could take now, which one will I regret NOT taking,
    given who is likely to still be there when I pick again?

That is opportunity cost, and it needs three things VORP alone doesn't have:

1. **Your exact pick schedule.** In a snake draft the gap between your turns
   swings wildly. At slot 1 in a 10-team league you wait 18 picks; at slot 10
   you wait 2, then 18. A player worth reaching for at slot 1 is a player you
   can comfortably wait on at slot 10.

2. **What the market thinks.** FPL publishes `draft_rank`, its own preseason
   ordering, which is the best available proxy for where your league-mates will
   take people. A player your model rates 12th but the market rates 40th is
   someone you can wait a round on. The reverse is a player you will never get.

3. **Survival probability.** Combining 1 and 2: given N picks before your next
   turn and a player sitting k-deep in the market's ordering, how likely is he
   to still be there? From that you get the expected best player available at
   each position next turn, and the gain from taking someone now is:

       gain = his VORP  -  expected best VORP at his position next turn

How much to lean on that, measured rather than assumed
------------------------------------------------------

The tempting move is to draft purely by gain. Tested, that loses. Scoring by
`vorp + LOOKAHEAD * gain` across paired simulations (same slot, same seed, same
rivals, only the strategy changed), measured in starting-XI points:

    LOOKAHEAD   rivals follow ADP   rivals value players
      0.15            -1.0                 -2.9
      0.30            +0.8 to +3.2         -6.6
      0.50            +0.5                 -9.6
      1.00           -10.8                -15.2

Read that honestly. The tilt is worth roughly nothing against sharp opponents
and marginally positive against opponents who follow the published rankings,
which is well inside the noise of the projections underneath it. Pure
opportunity cost (1.0) is clearly bad. So the weight stays low, and set it to
0.0 for plain VORP if you prefer.

What is NOT marginal, in the same tests, is VORP itself: drafting by highest
projected points instead costs 35 to 68 starting-XI points, and loses 98 times
out of 100. The positional framing is where the edge lives; the lookahead tilt
is a rounding error on top of it.

The genuinely useful output here is the survival probability and the market
comparison shown on each row. A human reads "he is 100% to still be there in 12
picks, and the market has him 60 spots below your board" far better than any
weight this file could apply automatically.

The round shape everyone talks about (midfielders and forwards early, keeper
late) is not hardcoded anywhere. It falls out of where the VORP cliffs are.
"""

from __future__ import annotations

import math

from model import SQUAD_LIMITS, Player

POS = ["GKP", "DEF", "MID", "FWD"]
ROUNDS = sum(SQUAD_LIMITS.values())  # 15

# How hard to tilt away from best-available toward positional scarcity.
# 0.0 = pure VORP, 1.0 = pure opportunity cost. Empirically 0.3 is the peak;
# see the module docstring for the numbers. Deliberately low.
LOOKAHEAD = 0.30


# ------------------------------------------------------------ pick schedule --

def snake_picks(slot: int, n_teams: int, rounds: int = ROUNDS) -> list[int]:
    """Overall pick numbers (1-based) for a manager at `slot` in a snake draft.

    Round 1 runs 1..N, round 2 runs N..1, and so on.
    """
    picks = []
    for r in range(rounds):
        if r % 2 == 0:
            picks.append(r * n_teams + slot)
        else:
            picks.append(r * n_teams + (n_teams - slot + 1))
    return picks


def picks_until_next(slot: int, n_teams: int, picks_made: int,
                     rounds: int = ROUNDS) -> tuple[int, int, int]:
    """Return (your_next_pick_no, following_pick_no, gap_between_them).

    `picks_made` is how many players have come off the board in total.
    """
    sched = snake_picks(slot, n_teams, rounds)
    upcoming = [p for p in sched if p > picks_made]
    if not upcoming:
        return (0, 0, 0)
    nxt = upcoming[0]
    following = upcoming[1] if len(upcoming) > 1 else nxt
    return (nxt, following, max(0, following - nxt - 1))


# ---------------------------------------------------- market / survival model --

def survival_probs(avail: list[Player], gap: int) -> dict[int, float]:
    """P(each available player is still there after `gap` more picks).

    Drafters follow the published ordering loosely, so a player sitting k-deep
    in the market's list when `gap` picks are about to happen is very likely
    gone if k < gap and very likely safe if k > gap. The logistic width `s`
    is the amount of noise in that behaviour: with a bigger gap there is more
    room for the order to scramble, so the curve flattens.
    """
    if gap <= 0:
        return {p.draft_id: 1.0 for p in avail}

    # Rank available players by the market's ordering. Anyone without a
    # draft_rank goes to the back, which is where undrafted players belong.
    ordered = sorted(avail, key=lambda p: (p.draft_rank is None,
                                           p.draft_rank or 10 ** 6))
    s = max(2.0, 0.32 * gap)
    out = {}
    for k, p in enumerate(ordered):
        # k is 0-based depth in the market list; gap is how many picks happen.
        z = (gap - k) / s
        z = max(-40.0, min(40.0, z))
        p_gone = 1.0 / (1.0 + math.exp(-z))
        out[p.draft_id] = 1.0 - p_gone
    return out


def expected_best_next(avail: list[Player], surv: dict[int, float],
                       pos: str) -> float:
    """Expected VORP of the best player at `pos` still there at your next turn.

    Walk the position's candidates best-first. The best one contributes his
    VORP times his chance of surviving; the second contributes his, times his
    survival, times the chance the first is gone; and so on.
    """
    cands = sorted([p for p in avail if p.pos == pos],
                   key=lambda p: p.vorp, reverse=True)[:40]
    exp = 0.0
    none_yet = 1.0
    for p in cands:
        s = surv.get(p.draft_id, 0.0)
        exp += p.vorp * s * none_yet
        none_yet *= (1.0 - s)
        if none_yet < 1e-4:
            break
    # If everyone is gone you are at replacement level, which is VORP 0.
    return exp


# ------------------------------------------------------------ recommendation --

def recommend(players: list[Player], gone: set[int], mine: set[int],
              slot: int, n_teams: int, top_n: int = 12) -> dict:
    """Rank the legal picks by opportunity cost."""
    avail = [p for p in players if p.draft_id not in gone
             and p.draft_id not in mine]
    picks_made = len(gone) + len(mine)
    nxt, following, gap = picks_until_next(slot, n_teams, picks_made)

    counts = {pos: 0 for pos in POS}
    for p in players:
        if p.draft_id in mine:
            counts[p.pos] += 1
    needs = {pos: SQUAD_LIMITS[pos] - counts[pos] for pos in POS}
    rounds_left = sum(needs.values())

    # Round comes from where the draft actually is, not from how many players
    # you hold, so it stays correct if you only log other managers' picks.
    round_no = min(ROUNDS, -(-nxt // n_teams)) if nxt else ROUNDS

    eligible = [p for p in avail if needs[p.pos] > 0]
    if not eligible or rounds_left == 0:
        return {"picks": [], "needs": needs, "next": nxt, "gap": gap,
                "round": round_no, "counts": counts}

    surv = survival_probs(avail, gap)
    exp_next = {pos: expected_best_next(avail, surv, pos)
                for pos in POS if needs[pos] > 0}

    # Market ranking of your model, so we can show where you are getting value.
    by_vorp = sorted(avail, key=lambda p: p.vorp, reverse=True)
    vorp_rank = {p.draft_id: i + 1 for i, p in enumerate(by_vorp)}
    by_adp = sorted(avail, key=lambda p: (p.draft_rank is None,
                                          p.draft_rank or 10 ** 6))
    adp_rank = {p.draft_id: i + 1 for i, p in enumerate(by_adp)}

    scored = []
    for p in eligible:
        gain = p.vorp - exp_next.get(p.pos, 0.0)
        # Best-available is the baseline; scarcity only tilts it. Drafting on
        # gain alone tested worse than plain VORP, so it gets a small weight.
        score = p.vorp + LOOKAHEAD * gain
        # Being unable to fill a position later is a real cost neither figure
        # captures, so nudge toward positions you are furthest from completing.
        score *= 1.0 + 0.02 * (needs[p.pos] - 1)
        scored.append({
            "p": p,
            "score": score,
            "gain": gain,
            "survive": surv.get(p.draft_id, 0.0),
            "exp_next": exp_next.get(p.pos, 0.0),
            "vorp_rank": vorp_rank.get(p.draft_id, 999),
            "adp_rank": adp_rank.get(p.draft_id, 999),
        })
    scored.sort(key=lambda d: d["score"], reverse=True)

    return {
        "picks": scored[:top_n],
        "needs": needs,
        "counts": counts,
        "next": nxt,
        "following": following,
        "gap": gap,
        "round": round_no,
        "exp_next": exp_next,
        "picks_made": picks_made,
    }


def explain(entry: dict, needs: dict) -> list[str]:
    """Short reasons a pick is being recommended, for display."""
    p = entry["p"]
    why = []
    edge = p.vorp - entry["exp_next"]
    if edge > 12:
        why.append(f"{edge:.0f} pts better than what {p.pos} offers next turn")
    if entry["survive"] < 0.30:
        why.append(f"only {entry['survive'] * 100:.0f}% to last until your next pick")
    elif entry["survive"] > 0.80 and edge < 12:
        why.append(f"{entry['survive'] * 100:.0f}% likely to still be here, "
                   f"so you can wait")
    slide = entry["adp_rank"] - entry["vorp_rank"]
    if slide > 12:
        why.append(f"market has him {slide} spots lower than your board")
    elif slide < -12:
        why.append(f"market rates him {-slide} spots higher than your board")
    if "PENS" in p.flags:
        why.append("penalties")
    if "DEFCON" in p.flags:
        why.append("high defensive contribution")
    if needs.get(p.pos, 0) >= 3:
        why.append(f"need {needs[p.pos]} more {p.pos}")
    return why


def round_plan(players: list[Player], n_teams: int) -> list[tuple[int, str]]:
    """A rough positional shape for the draft, derived from the board itself.

    Simulates a draft where every manager takes the highest-VORP legal player,
    then reports which position your slot ends up taking each round. This is
    descriptive, not prescriptive: it shows where the value actually sits given
    the projections, rather than a rule of thumb someone typed in.
    """
    pool = sorted(players, key=lambda p: p.vorp, reverse=True)
    taken: set[int] = set()
    squads = {s: {pos: 0 for pos in POS} for s in range(1, n_teams + 1)}
    plan: list[tuple[int, str]] = []

    for r in range(ROUNDS):
        seats = list(range(1, n_teams + 1))
        if r % 2:
            seats.reverse()
        for seat in seats:
            need = {pos: SQUAD_LIMITS[pos] - squads[seat][pos] for pos in POS}
            pick = next((p for p in pool
                         if p.draft_id not in taken and need[p.pos] > 0), None)
            if pick is None:
                continue
            taken.add(pick.draft_id)
            squads[seat][pick.pos] += 1
            if seat == 1:
                plan.append((r + 1, pick.pos))
    return plan
