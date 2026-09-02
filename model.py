"""
Projection + VORP model for FPL Draft.

Why VORP and not "points"?

In Classic FPL you have a budget, so value = points per million. In Draft there
is no budget at all. Every pick costs you exactly one thing: the pick itself.
So the only question that matters is "how many points does this player give me
over the guy I could get instead at the same position later?"

That difference is VORP (Value Over Replacement Player). Replacement level is
the projected output of the last player at each position who will realistically
be in someone's starting XI. A forward projected for 140 points when the 17th
best forward gets 110 is worth *less* than a defender projected for 125 when
the 33rd best defender gets 70.

This is the single biggest edge you can have in a draft, because most people
draft off a flat "best player available" list and systematically overdraft
forwards and midfielders.

Preseason caveat
----------------
Before Gameweek 1 every counting stat in the bootstrap feed (total_points,
form, minutes, xG) is reset to zero. So the projection leans on the signals
that DO exist preseason:

  * now_cost from the Classic game - FPL's own paid valuation of a player
  * draft_rank from the Draft game - FPL's own preseason draft ordering
  * ep_next - FPL's expected points for the coming round
  * set-piece order fields - penalties, corners, direct free kicks
  * status / chance_of_playing - injuries and suspensions
  * last season's totals, if you ran with --deep

A note on fixtures: the next five fixture difficulties are shown on the board
but are NOT folded into the projection. Over 38 games everyone plays everyone,
so an easy opening run barely moves a season total. It matters for who you
start in week one and for waiver timing, which is a decision you make with your
eyes, not something that should quietly reweight a draft board.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

# FPL Draft default squad: 2 GK, 5 DEF, 5 MID, 3 FWD = 15.
SQUAD_LIMITS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}

# Typical number of each position a manager actually *starts* each week.
# Draft formations allow 3-5 DEF, 2-5 MID, 1-3 FWD around a single keeper.
# These averages set where replacement level sits.
TYPICAL_STARTERS = {"GKP": 1.0, "DEF": 4.0, "MID": 4.0, "FWD": 2.0}

# Season-points curve per position, as (rank, projected points) anchor points.
# Ranks are within position across the whole league. Values between anchors are
# linearly interpolated; past the last anchor the value is held flat.
#
# These are calibrated to what real FPL Draft seasons look like: the very top
# midfielders clear 240+, the last starting midfielder in an eight-team league
# is around 110, and third-choice players sit in the 30s. The *shape* matters
# far more than the exact numbers, because VORP only cares about differences.
POS_CURVE = {
    "GKP": [(1, 165), (4, 148), (8, 130), (14, 115), (20, 105), (35, 60), (60, 35)],
    "DEF": [(1, 175), (5, 150), (12, 130), (24, 115), (32, 108), (50, 88),
            (70, 72), (110, 45), (160, 30)],
    "MID": [(1, 250), (3, 215), (8, 180), (16, 145), (32, 112), (50, 92),
            (80, 72), (120, 48), (170, 32)],
    "FWD": [(1, 225), (3, 190), (6, 165), (10, 140), (16, 120), (25, 95),
            (45, 68), (70, 45), (100, 30)],
}


def curve_points(pos: str, rank: int) -> float:
    """Projected season points for the Nth best player at a position."""
    anchors = POS_CURVE.get(pos)
    if not anchors:
        return max(30.0, 200.0 - rank * 1.5)
    if rank <= anchors[0][0]:
        return float(anchors[0][1])
    for (r0, v0), (r1, v1) in zip(anchors, anchors[1:]):
        if rank <= r1:
            span = r1 - r0
            t = (rank - r0) / span if span else 0.0
            return float(v0 + (v1 - v0) * t)
    return float(anchors[-1][1])


def _norm_name(s: str) -> str:
    """Fold a name down to something typeable.

    Accents are stripped so 'Odegaard' finds 'Ødegaard'. Hyphens become spaces
    so 'alexander arnold' and 'Alexander-Arnold' land on the same key, while
    apostrophes are dropped outright so 'oriley' finds "O'Riley". Digits are
    kept, since dropping them would collapse otherwise distinct keys.
    """
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ø", "o").replace("Ø", "O").replace("ł", "l").replace("Ł", "L")
    s = s.replace("æ", "ae").replace("ß", "ss").replace("đ", "d")
    s = s.lower().replace("-", " ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Player:
    draft_id: int
    code: int
    name: str
    full_name: str
    pos: str
    team: str
    team_short: str
    price: float                 # Classic FPL price, used as a signal only
    draft_rank: int | None
    ep_next: float
    status: str
    chance: float                # 0.0 - 1.0 availability multiplier
    news: str
    pens: int | None             # penalties_order, 1 = first choice
    corners: int | None
    freekicks: int | None
    last_season_pts: int | None
    last_season_mins: int | None
    defcon_last: float | None = None   # prior-season defensive contribution pts
    defcon_p90: float = 0.0            # and the same figure per 90 minutes
    fdr: list[int] = field(default_factory=list)   # next 5 fixture difficulties
    fdr_avg: float = 3.0
    start_pct: float = 0.0             # rough chance he starts a given week
    sleeper: dict | None = None        # curated note, see sleepers.py
    # --- filled in by season.py once real matches exist ---
    season_minutes: float = 0.0
    season_starts: float = 0.0
    season_points: float = 0.0
    form: float = 0.0
    start_rate: float = 0.0            # starts / gameweeks played, observed
    p90: float = 0.0                   # points per 90, shrunk toward baseline
    dc_p90: float = 0.0                # defensive actions per 90
    dc_hit: float = 0.0                # estimated share of matches clearing it
    exp_minutes: float = 0.0
    proj_week: float = 0.0             # projected points next gameweek
    proj: float = 0.0            # projected season points
    vorp: float = 0.0
    tier: int = 0
    flags: list[str] = field(default_factory=list)

    @property
    def search_keys(self) -> list[str]:
        return [_norm_name(self.name), _norm_name(self.full_name)]


def next_fixtures(snap: dict, n: int = 5) -> dict[int, list[int]]:
    """Next `n` fixture difficulties for every team id.

    FPL publishes a 1-5 difficulty for each side of each fixture, so a team's
    upcoming run is just their own side's number in date order. 1 and 2 are
    kind, 3 is neutral, 4 and 5 are hard.
    """
    out: dict[int, list[int]] = {}
    fixtures = [f for f in (snap.get("fixtures") or [])
                if not f.get("finished") and f.get("event") is not None]
    fixtures.sort(key=lambda f: (f.get("event") or 0,
                                 f.get("kickoff_time") or ""))
    for f in fixtures:
        for side, diff in (("team_h", "team_h_difficulty"),
                           ("team_a", "team_a_difficulty")):
            t = f.get(side)
            d = f.get(diff)
            if t is None or d is None:
                continue
            out.setdefault(t, [])
            if len(out[t]) < n:
                out[t].append(int(d))
    return out


def _defcon_points(season: dict, minutes: int | None) -> float | None:
    """Prior-season defensive contribution points, if the feed carries them.

    Defensive contribution arrived in 2025/26 and continues unchanged in
    2026/27: a defender banks 2 points for 10+ clearances, blocks,
    interceptions and tackles in a match; a midfielder or forward needs 12 of
    those plus ball recoveries. It is capped at 2 points per match.

    The history feed has carried this under a couple of names, and older
    seasons don't have it at all, so probe for it and sanity-check the
    magnitude. A season total above 2 points per appearance means the field is
    counting raw defensive actions rather than points, so convert.
    """
    for key in ("defensive_contribution", "defensive_contributions",
                "defcon", "defensive_contribution_points"):
        if key in season and season[key] is not None:
            try:
                val = float(season[key])
            except (TypeError, ValueError):
                continue
            if val <= 0:
                return 0.0
            apps = max(1.0, (minutes or 0) / 90.0)
            if val / apps > 2.0:
                # Raw action counts: assume the threshold was cleared in
                # roughly the share of matches implied by the average.
                return min(2.0 * apps, val / 10.0 * 2.0)
            return val
    return None


def _availability(status: str, chance) -> tuple[float, list[str]]:
    """Turn injury/suspension fields into a 0-1 multiplier plus a note."""
    flags: list[str] = []
    if chance is not None:
        try:
            pct = float(chance) / 100.0
        except (TypeError, ValueError):
            pct = None
        if pct is not None and pct < 1.0:
            flags.append(f"{int(pct * 100)}% fit")
            # A short-term knock costs less than the raw percentage suggests,
            # because it usually only affects a couple of gameweeks.
            return 0.55 + 0.45 * pct, flags

    mult = {
        "a": 1.0,   # available
        "d": 0.80,  # doubtful
        "i": 0.45,  # injured
        "s": 0.55,  # suspended
        "u": 0.05,  # unavailable / left the league
        "n": 0.25,  # not in squad
    }.get((status or "a").lower(), 1.0)

    if mult < 1.0:
        flags.append({"d": "doubtful", "i": "injured", "s": "suspended",
                      "u": "unavailable", "n": "not in squad"}.get(status, status))
    return mult, flags


def _zscores(values: list[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    sd = math.sqrt(var) or 1.0
    return [(v - mean) / sd for v in values]


def build_players(snap: dict) -> list[Player]:
    draft = snap["draft"]
    classic = snap["classic"]
    past = snap.get("past") or {}

    pos_by_id = {t["id"]: t["singular_name_short"]
                 for t in draft.get("element_types", [])}
    team_by_id = {t["id"]: (t.get("name", "?"), t.get("short_name", "?"))
                  for t in draft.get("teams", [])}

    # Classic feed keyed by the stable cross-game player code.
    classic_by_code = {e["code"]: e for e in classic.get("elements", [])}
    fdr_by_team = next_fixtures(snap)

    players: list[Player] = []
    for e in draft.get("elements", []):
        code = e.get("code")
        c = classic_by_code.get(code, {})

        pos = pos_by_id.get(e.get("element_type"), "?")
        team_name, team_short = team_by_id.get(e.get("team"), ("?", "?"))

        # Last completed season, if we pulled history.
        last_pts = last_mins = None
        defcon = None
        hist = past.get(str(c.get("id"))) if c else None
        if hist:
            prev = hist[-1]
            last_pts = prev.get("total_points")
            last_mins = prev.get("minutes")
            defcon = _defcon_points(prev, last_mins)

        chance_raw = e.get("chance_of_playing_next_round")
        mult, flags = _availability(e.get("status", "a"), chance_raw)

        try:
            ep = float(e.get("ep_next") or c.get("ep_next") or 0.0)
        except (TypeError, ValueError):
            ep = 0.0

        players.append(Player(
            draft_id=e["id"],
            code=code,
            name=e.get("web_name", "?"),
            full_name=f"{e.get('first_name','')} {e.get('second_name','')}".strip(),
            pos=pos,
            team=team_name,
            team_short=team_short,
            price=(c.get("now_cost", 0) or 0) / 10.0,
            draft_rank=e.get("draft_rank"),
            ep_next=ep,
            status=e.get("status", "a"),
            chance=mult,
            news=e.get("news", "") or "",
            pens=e.get("penalties_order"),
            corners=e.get("corners_and_indirect_freekicks_order"),
            freekicks=e.get("direct_freekicks_order"),
            last_season_pts=last_pts,
            last_season_mins=last_mins,
            defcon_last=defcon,
            defcon_p90=(defcon / (last_mins / 90.0)
                        if defcon and last_mins and last_mins > 600 else 0.0),
            fdr=fdr_by_team.get(e.get("team"), []),
            flags=flags,
        ))
    for p in players:
        p.fdr_avg = (sum(p.fdr) / len(p.fdr)) if p.fdr else 3.0
    _estimate_start_pct(players)
    return players


def _estimate_start_pct(players: list[Player]) -> None:
    """Rough chance a fit player is in the starting XI on a given week.

    There is no "will he start" field in the API, so this is assembled from
    three things that between them say most of it:

      * where he sits in his club's pecking order at his position, proxied by
        price. Clubs' best players cost the most, and FPL reprices toward role.
      * how many minutes he actually played last season, when we have it.
      * his availability, which already folds in injuries and suspensions.

    It is an estimate and labelled as one. Its job is to stop you drafting a
    backup who will never see the pitch, not to predict rotation precisely.
    """
    by_club_pos: dict[tuple[str, str], list[Player]] = {}
    for p in players:
        by_club_pos.setdefault((p.team_short, p.pos), []).append(p)

    for group in by_club_pos.values():
        group.sort(key=lambda x: x.price, reverse=True)
        # How many of this position a club typically starts.
        slots = {"GKP": 1, "DEF": 4, "MID": 4, "FWD": 2}
        for i, p in enumerate(group):
            n_start = slots.get(p.pos, 3)
            if i < n_start:
                base = 0.90 - 0.06 * i          # clear first choices
            else:
                base = max(0.05, 0.55 - 0.16 * (i - n_start + 1))

            # Real minutes beat any depth-chart guess.
            if p.last_season_mins is not None:
                played = min(1.0, p.last_season_mins / 2600.0)
                base = 0.45 * base + 0.55 * played

            p.start_pct = round(max(0.0, min(1.0, base * p.chance)), 2)


def project(players: list[Player]) -> None:
    """Fill in .proj for every player, in place."""
    by_pos: dict[str, list[Player]] = {}
    for p in players:
        # Re-projecting should not stack duplicate flags; keep only the
        # availability notes, which were set when the Player was built.
        p.flags = [f for f in p.flags if f not in
                   ("PENS", "corners", "FKs", "no PL history", "DEFCON")]
        by_pos.setdefault(p.pos, []).append(p)

    for pos, group in by_pos.items():
        # --- Blend the available preseason signals into one ranking score ---
        prices = [p.price for p in group]
        # draft_rank is 1 = best, so negate it to make bigger = better.
        ranks = [-(p.draft_rank if p.draft_rank else 9999) for p in group]
        eps = [p.ep_next for p in group]

        zp, zr, ze = _zscores(prices), _zscores(ranks), _zscores(eps)

        # Last season points per 90, where we have it. Players with real
        # top-flight minutes get anchored to what they actually produced.
        pp90 = []
        for p in group:
            if p.last_season_pts and p.last_season_mins and p.last_season_mins > 600:
                pp90.append(p.last_season_pts / (p.last_season_mins / 90.0))
            else:
                pp90.append(float("nan"))
        have_hist = [v for v in pp90 if not math.isnan(v)]
        zh = _zscores(have_hist) if have_hist else []
        hist_iter = iter(zh)
        zhist = [next(hist_iter) if not math.isnan(v) else None for v in pp90]

        # Defensive contribution, as a per-90 rate. Worth 2 points a match and
        # largely independent of whether the team is any good, which makes it
        # the most reliable points source available to a defender. Weighted
        # hardest at DEF, where the 10-action threshold is easier to clear and
        # the rest of the scoring is thin, and lightly for MID where the bar is
        # 12 actions and attacking returns dominate anyway.
        dc_w = {"DEF": 0.20, "MID": 0.08, "FWD": 0.02, "GKP": 0.0}.get(pos, 0.0)
        dc_vals = [p.defcon_p90 for p in group]
        zd = _zscores(dc_vals) if any(v > 0 for v in dc_vals) else [0.0] * len(group)

        scores = []
        for i, p in enumerate(group):
            if zhist[i] is not None:
                # Returning Premier League player: trust what he actually did,
                # but keep price in the mix because it encodes transfers,
                # role changes and manager intent that last season cannot.
                # The defensive-contribution slice is carved out of the
                # last-season weight, since it is a component of that total.
                s = (0.42 * zp[i] + 0.20 * zr[i] + 0.08 * ze[i]
                     + (0.30 - dc_w) * zhist[i] + dc_w * zd[i])
            else:
                # Newly promoted or newly signed: no usable top-flight history,
                # so lean on the market's valuation and FPL's own draft rank.
                s = 0.58 * zp[i] + 0.32 * zr[i] + 0.10 * ze[i]
                p.flags.append("no PL history")
            scores.append(s)

        # Flag the genuine defensive-contribution specialists so they stand out
        # on the board. These are the players whose floor is highest.
        if dc_w > 0 and any(v > 0 for v in dc_vals):
            cutoff = sorted(dc_vals, reverse=True)[max(0, len(dc_vals) // 8)]
            for i, p in enumerate(group):
                if p.defcon_p90 >= cutoff and p.defcon_p90 > 0:
                    p.flags.append("DEFCON")

        # --- Map the ranking onto a realistic season-points curve ---
        order = sorted(range(len(group)), key=lambda i: scores[i], reverse=True)

        for slot, idx in enumerate(order):
            p = group[idx]
            base = curve_points(pos, slot + 1)

            # Set-piece duties are worth real, knowable points.
            bonus = 0.0
            if p.pens == 1:
                bonus += 22.0 if pos in ("FWD", "MID") else 14.0
                p.flags.append("PENS")
            elif p.pens == 2:
                bonus += 5.0
            if p.corners == 1:
                bonus += 10.0 if pos in ("MID", "DEF") else 5.0
                p.flags.append("corners")
            if p.freekicks == 1:
                bonus += 7.0
                p.flags.append("FKs")

            # start_pct already contains the injury/suspension multiplier, so
            # this replaces the old `chance` term rather than stacking on it.
            # At a nailed 1.0 it is neutral; a fringe player at 0.2 loses more
            # than half his projection, which is the direction you want to err.
            p.proj = (base + bonus) * (0.30 + 0.70 * p.start_pct)


def compute_vorp(players: list[Player], n_teams: int,
                 available_only: list[Player] | None = None) -> None:
    """Set .vorp for every player relative to current replacement level.

    Replacement level is recomputed from whoever is still on the board, which
    is what makes the recommendation shift as positions dry up during a draft.
    """
    pool = available_only if available_only is not None else players

    repl: dict[str, float] = {}
    for pos, starters in TYPICAL_STARTERS.items():
        group = sorted([p for p in pool if p.pos == pos],
                       key=lambda x: x.proj, reverse=True)
        if not group:
            repl[pos] = 0.0
            continue
        idx = min(int(round(starters * n_teams)), len(group) - 1)
        repl[pos] = group[idx].proj

    for p in players:
        p.vorp = p.proj - repl.get(p.pos, 0.0)

    # Tiers: group players whose VORP is close together, so you can see where
    # the real cliffs are. Inside a tier, take the guy you like; between tiers,
    # the drop is worth reaching for.
    for pos in TYPICAL_STARTERS:
        group = sorted([p for p in pool if p.pos == pos],
                       key=lambda x: x.vorp, reverse=True)
        tier = 1
        for i, p in enumerate(group):
            if i > 0:
                gap = group[i - 1].vorp - p.vorp
                if gap > 8.0:
                    tier += 1
            p.tier = tier


def replacement_levels(players: list[Player], n_teams: int) -> dict[str, float]:
    out = {}
    for pos, starters in TYPICAL_STARTERS.items():
        group = sorted([p for p in players if p.pos == pos],
                       key=lambda x: x.proj, reverse=True)
        if not group:
            out[pos] = 0.0
            continue
        idx = min(int(round(starters * n_teams)), len(group) - 1)
        out[pos] = group[idx].proj
    return out
