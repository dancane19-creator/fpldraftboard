"""Curated draft targets, matched onto the live player list by name.

These come from the research in SLEEPERS.md. They are deliberately NOT fed into
the projection: a hand-typed opinion should not silently move a number. They
show up as a badge and a note so you can see the case and decide, which is the
only honest way to mix an editorial view with a model.

`tier` controls how loudly it shows:
    1  worth an actual pick
    2  waiver-wire target or late flier
    0  avoid, shown as a warning
"""

from __future__ import annotations

import unicodedata

# key = surname or the distinctive part of the FPL web name, lowercased
NOTES: dict[str, dict] = {
    # ---- defensive contribution specialists, the biggest edge in Draft ----
    "senesi":      {"tier": 1, "tag": "DEFCON", "note": "70.3% defcon hit rate, highest of any defender"},
    "hill":        {"tier": 2, "tag": "DEFCON", "note": "63.6% defcon hit rate"},
    "andersen":    {"tier": 1, "tag": "DEFCON", "note": "60.6% defcon rate on a side that defends deep"},
    "tarkowski":   {"tier": 1, "tag": "DEFCON", "note": "59.5% defcon rate, solid Everton defence"},
    "ballard":     {"tier": 2, "tag": "DEFCON", "note": "58.3% defcon hit rate"},
    "garner":      {"tier": 1, "tag": "TARGET", "note": "52.6% defcon AND Everton free kicks and corners"},
    "anderson":    {"tier": 1, "tag": "DEFCON", "note": "70.3%, highest midfield defcon rate, now at City"},
    "ampadu":      {"tier": 2, "tag": "DEFCON", "note": "54.3% defcon rate, cheap source of the same thing"},
    "phillips":    {"tier": 2, "tag": "DEFCON", "note": "47.8% defcon rate"},

    # ---- promoted clubs ----
    "davis":       {"tier": 1, "tag": "SLEEPER", "note": "18 assists in promotion season, on corners, kind opening fixtures"},
    "ewijk":       {"tier": 1, "tag": "SLEEPER", "note": "8-10 assists, takes direct free kicks, nailed at right back"},
    "mcburnie":    {"tier": 2, "tag": "SLEEPER", "note": "17 goals, sole penalty taker, nailed lone striker"},
    "hughes":      {"tier": 2, "tag": "WAIVER", "note": "11.8 defensive actions per 90, best of any promoted defender. OUT for GW1"},
    "wright":      {"tier": 2, "tag": "SLEEPER", "note": "17 Championship goals, on penalties"},
    "thomas":      {"tier": 2, "tag": "SLEEPER", "note": "3 goals 4 assists from centre back, set-piece threat"},
    "torp":        {"tier": 2, "tag": "WATCH", "note": "second on Coventry penalties, on free kicks and corners"},
    "giles":       {"tier": 2, "tag": "WATCH", "note": "8 Championship assists, on corners, but competing with Targett"},

    # ---- new signings worth knowing ----
    "sangare":     {"tier": 2, "tag": "WAIVER", "note": "14.2 defensive actions per 90 in Ligue 1, would rank 6th in the PL"},
    "vuskovic":    {"tier": 2, "tag": "FLIER", "note": "12.5 defensive actions per 90, 6 goals, rotation risk"},
    "garcia":      {"tier": 2, "tag": "WATCH", "note": "0.57 goals per 90 for Real Madrid, likely Fulham penalties"},

    # ---- value keepers, for your late pick ----
    "verbruggen":  {"tier": 2, "tag": "VALUE GK", "note": "130 pts last season, best efficiency in his bracket"},
    "kelleher":    {"tier": 2, "tag": "VALUE GK", "note": "143 pts, strong save volume"},

    # ---- traps ----
    "tzolis":      {"tier": 0, "tag": "AVOID", "note": "output projected to halve, Martinelli blocks the minutes"},
    "toure":       {"tier": 0, "tag": "AVOID", "note": "must displace Barnes first, assist projection more than halves"},
    "rudoni":      {"tier": 0, "tag": "AVOID", "note": "fitness unresolved"},
    "dasilva":     {"tier": 0, "tag": "AVOID", "note": "starting spot under threat"},
    "diop":        {"tier": 0, "tag": "AVOID", "note": "Kipre and Greaves are ahead of him in the predicted XI"},
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace("-", " ").replace("'", "").strip()


def annotate(players) -> int:
    """Attach notes to matching players. Returns how many matched.

    Matching is deliberately conservative: the key must appear as a whole word
    in the player's name. 'hill' should not match 'Hillhouse'. Where a surname
    is genuinely ambiguous across two players, both get the note and you read
    the text to work out which one it means.
    """
    hits = 0
    for p in players:
        words = set(_norm(p.name).split()) | set(_norm(p.full_name).split())
        for key, info in NOTES.items():
            if key in words:
                p.sleeper = info
                hits += 1
                break
    return hits
