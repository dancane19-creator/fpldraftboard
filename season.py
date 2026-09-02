"""In-season projection and waiver valuation.

The preseason model in model.py leans on price and draft rank because every
counting stat is zeroed before Gameweek 1. Once real matches exist that
scaffolding should come down: actual minutes, starts, form and underlying
numbers are strictly better evidence than FPL's own price tag.

This module takes over once `current_event` is set, and it answers a different
question from the draft board. In a draft the question was "who is worth a
pick". On waivers it is:

    How many points does this free agent add to MY team, given who I would
    actually be dropping or benching for him?

That is a different replacement level. During the draft, replacement was the
best player nobody in the league starts. On waivers, replacement is **your own
worst startable player at that position**. A free agent projected for 4.0 a
week is a huge add if your fifth defender is on 1.5, and worthless if he is on
4.2. Ranking by raw projection misses that completely, which is why most people
churn their bench for no gain.

Two other things the draft model could not do and this one can:

  * **Start rate is now observed, not estimated.** starts / team games played
    is a fact. A player at 2 starts from 2 is nailed; one at 0 from 2 who came
    off the bench twice is a trap however good his per-90 looks.
  * **Small samples need pulling toward a prior.** Two gameweeks is noise. A
    player on 10.0 points per game after two matches is not a 380-point player.
    Everything here is shrunk toward a positional baseline, hard early, less so
    as matches accumulate.
"""

from __future__ import annotations

from model import SQUAD_LIMITS, Player

# How many matches of evidence before per-90 output is trusted at face value.
# Below this the estimate is pulled toward the positional baseline in
# proportion to how little we have seen.
SHRINK_MATCHES = 8.0

# Points per 90 a replacement-level player at each position produces. Used as
# the shrink target, so a two-game wonder regresses toward something sane.
BASELINE_P90 = {"GKP": 3.2, "DEF": 3.0, "MID": 3.2, "FWD": 3.0}

# Defensive contribution thresholds, unchanged for 2026/27.
DC_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12, "GKP": 999}

# Used to turn the preseason model's full-season projection into a weekly
# rate for players with no in-season minutes to observe yet.
WEEKS_IN_SEASON = 38.0


def is_in_season(snap: dict) -> bool:
    game = snap.get("game") or {}
    ev = game.get("current_event")
    return bool(ev)


def current_event(snap: dict) -> int:
    return int((snap.get("game") or {}).get("current_event") or 0)


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def enrich(players: list[Player], snap: dict) -> None:
    """Attach observed season form to each player, in place.

    Adds: games, starts, start_rate, p90, dc_p90, dc_hit, proj_week.
    """
    gw = current_event(snap)
    draft_by_id = {e["id"]: e for e in (snap.get("draft") or {}).get("elements", [])}

    for p in players:
        e = draft_by_id.get(p.draft_id, {})
        mins = _f(e.get("minutes"))
        starts = _f(e.get("starts"))
        pts = _f(e.get("total_points"))
        dc = _f(e.get("defensive_contribution"))

        p.season_minutes = mins
        p.season_starts = starts
        p.season_points = pts
        p.form = _f(e.get("form"))

        # Start rate against the gameweeks actually played so far. Capped at 1
        # because a doubled gameweek would otherwise push it past 100%.
        p.start_rate = min(1.0, starts / gw) if gw else 0.0

        # Points per 90, shrunk toward the positional baseline. With two games
        # played the estimate is roughly 80% baseline, which is the honest
        # weighting for that little evidence.
        nineties = mins / 90.0
        raw_p90 = (pts / nineties) if nineties > 0.3 else 0.0
        w = min(1.0, nineties / SHRINK_MATCHES)
        base = BASELINE_P90.get(p.pos, 3.0)
        p.p90 = w * raw_p90 + (1.0 - w) * base if nineties > 0 else 0.0

        # Defensive actions per 90, and a crude estimate of how often that
        # clears the 2-point threshold. The feed gives a season total of raw
        # actions, not per-match, so this cannot see variance within it.
        p.dc_p90 = (dc / nineties) if nineties > 0.3 else 0.0
        thr = DC_THRESHOLD.get(p.pos, 999)
        p.dc_hit = max(0.0, min(0.95, (p.dc_p90 - thr * 0.55) / (thr * 0.75))) \
            if p.dc_p90 > 0 else 0.0

        # Expected minutes next week. Availability is already a 0-1 multiplier.
        exp_mins = 90.0 * p.start_rate * p.chance
        if p.start_rate < 0.5 and mins > 0:
            # A rotation player still gets some minutes off the bench.
            exp_mins = max(exp_mins, min(35.0, mins / max(1.0, gw)))
        p.exp_minutes = exp_mins
        p.proj_week = p.p90 * (exp_mins / 90.0)

        # A player with zero minutes this season has no start_rate to trust -
        # not necessarily because he is out of favour, but because a new
        # signing, a transfer into the league, or a long-term injury return
        # has no observed sample yet. Falling straight to 0 makes him
        # disappear from free-agent lists exactly when he might be the best
        # speculative pickup available.
        #
        # p.proj is the preseason model's full-season estimate, already
        # blending price, FPL's own draft_rank, ep_next and (for anyone with
        # a top-flight track record) last season's output, then discounted by
        # expected start share - it is the "FPL ranking method" signal,
        # not just next week's number. ep_next alone tends to lowball a
        # fresh transfer or new signing because FPL's live model has no
        # current-club sample either, so take whichever of the two paints
        # the more optimistic, better-informed picture rather than the more
        # conservative one.
        if mins == 0 and (p.ep_next > 0 or p.proj > 0):
            from_draft_model = (p.proj / WEEKS_IN_SEASON) if p.proj > 0 else 0.0
            from_next_round = p.ep_next * p.chance
            p.proj_week = max(from_draft_model, from_next_round)
            if "NEW" not in p.flags:
                p.flags = p.flags + ["NEW"]


def my_replacement(my_squad: list[Player], pos: str) -> float:
    """Weekly points of the man a new signing would actually displace.

    Not the worst player you own at the position, because you might be
    carrying a legitimate bench player. It is the weakest of those you would
    field, which is what a new arrival has to beat to change anything.
    """
    starters = {"GKP": 1, "DEF": 4, "MID": 4, "FWD": 2}
    group = sorted([p for p in my_squad if p.pos == pos],
                   key=lambda x: x.proj_week, reverse=True)
    if not group:
        return 0.0
    n = min(starters.get(pos, 3), len(group))
    return group[n - 1].proj_week


def waiver_targets(players: list[Player], owned: set[int], my_ids: set[int],
                   pinned: set[int] | None = None) -> list[dict]:
    """Rank free agents by what they would actually add to your team."""
    pinned = pinned or set()
    my_squad = [p for p in players if p.draft_id in my_ids]
    free = [p for p in players if p.draft_id not in owned]

    repl = {pos: my_replacement(my_squad, pos) for pos in SQUAD_LIMITS}

    out = []
    for p in free:
        gain = p.proj_week - repl.get(p.pos, 0.0)
        # A player who does not start cannot help, however good his rate is.
        confidence = p.start_rate * p.chance
        out.append({
            "p": p,
            "gain": gain,
            "gain_season": gain * 36,          # rough rest-of-season value
            "replaces": repl.get(p.pos, 0.0),
            "confidence": confidence,
            "pinned": p.draft_id in pinned,
        })

    # Pinned players sort to the top regardless of score, because a long shot
    # you want first still costs nothing: if he is gone the claim falls through
    # to the next one on the list.
    out.sort(key=lambda d: (d["pinned"], d["gain"]), reverse=True)
    return out


def drop_candidates(players: list[Player], my_ids: set[int]) -> list[Player]:
    """Your own squad, weakest first, for deciding who makes way."""
    mine = [p for p in players if p.draft_id in my_ids]
    return sorted(mine, key=lambda p: (p.proj_week, p.start_rate))
