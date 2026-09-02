"""Generate a snapshot with the same shape as the real API responses.

This exists so the board logic can be exercised end to end without network
access. The field names, types and value ranges mirror what
draft.premierleague.com/api/bootstrap-static and
fantasy.premierleague.com/api/bootstrap-static/ actually return.
"""

import json
import random

random.seed(7)

# Invented surnames, so a dry run looks like a real board instead of a wall of
# codes. They are deliberately not real Premier League players: attaching fake
# projections to real names would be worse than useless.
SURNAMES = [
    "Ashworth", "Bellamy", "Calderon", "Duarte", "Eriksen", "Farrow", "Gundal",
    "Halvorsen", "Ibsen", "Jankovic", "Keeler", "Lindqvist", "Marchetti",
    "Nkemba", "Ortega", "Pashley", "Quintero", "Rasmussen", "Sørli", "Tavares",
    "Uddin", "Vasquez", "Whitlock", "Ximenes", "Yilmaz", "Zabala", "Ainsley",
    "Broussard", "Castellan", "Draper", "Engberg", "Fontaine", "Grimaldi",
    "Haugen", "Ivarsson", "Jestrab", "Kowalski", "Lefevre", "Moretti",
    "Novak", "Okonkwo", "Petrov", "Rennick", "Salgado", "Thorne", "Ulvestad",
    "Verhoeven", "Wexler", "Yoshida", "Zieliński",
]
FIRSTS = [
    "Alex", "Bruno", "Callum", "Diogo", "Emil", "Felix", "Gabriel", "Henrik",
    "Ivan", "Joel", "Kenan", "Luca", "Mateo", "Nico", "Omar", "Pedro",
    "Rafael", "Stefan", "Tobias", "Viktor",
]
_used: set[str] = set()


def make_name(rng):
    """A unique-ish surname, with an initial when it would otherwise collide."""
    for _ in range(60):
        s = rng.choice(SURNAMES)
        if s not in _used:
            _used.add(s)
            return rng.choice(FIRSTS), s
    f = rng.choice(FIRSTS)
    return f, f"{rng.choice(SURNAMES)}-{rng.choice(SURNAMES)}"

TEAMS = [
    ("Arsenal", "ARS"), ("Aston Villa", "AVL"), ("Bournemouth", "BOU"),
    ("Brentford", "BRE"), ("Brighton", "BHA"), ("Chelsea", "CHE"),
    ("Coventry", "COV"), ("Crystal Palace", "CRY"), ("Everton", "EVE"),
    ("Fulham", "FUL"), ("Hull", "HUL"), ("Ipswich", "IPS"),
    ("Leeds", "LEE"), ("Liverpool", "LIV"), ("Man City", "MCI"),
    ("Man Utd", "MUN"), ("Newcastle", "NEW"), ("Nott'm Forest", "NFO"),
    ("Sunderland", "SUN"), ("Tottenham", "TOT"),
]

ELEMENT_TYPES = [
    {"id": 1, "singular_name_short": "GKP", "squad_select": 2},
    {"id": 2, "singular_name_short": "DEF", "squad_select": 5},
    {"id": 3, "singular_name_short": "MID", "squad_select": 5},
    {"id": 4, "singular_name_short": "FWD", "squad_select": 3},
]

# Squad shape per club: 3 GK, 8 DEF, 8 MID, 5 FWD = 24 -> 480 players.
SHAPE = {1: 3, 2: 8, 3: 8, 4: 5}
PRICE_BAND = {1: (4.0, 6.0), 2: (4.0, 7.5), 3: (4.5, 15.0), 4: (4.5, 15.0)}

draft_elements, classic_elements, past = [], [], {}
pid = 0

for t_idx, (name, short) in enumerate(TEAMS, start=1):
    # Club strength drives how good its players are, like the real thing.
    strength = random.uniform(0.25, 1.0)
    if short in ("COV", "HUL", "IPS"):
        strength = random.uniform(0.15, 0.35)  # promoted sides are weaker
    for etype, count in SHAPE.items():
        lo, hi = PRICE_BAND[etype]
        for j in range(count):
            pid += 1
            # Depth chart position: j == 0 is the first-choice player.
            depth = 1.0 / (1.0 + j * 0.55)
            quality = strength * depth
            price = round(lo + (hi - lo) * quality * random.uniform(0.7, 1.15), 1)
            price = max(4.0, min(price, hi))

            status = "a"
            chance = None
            roll = random.random()
            if roll > 0.94:
                status, chance = "i", 0
            elif roll > 0.89:
                status, chance = "d", 75

            pens = 1 if (j == 0 and etype in (3, 4) and random.random() > 0.6) else None
            corners = 1 if (j == 0 and etype in (2, 3) and random.random() > 0.7) else None
            fks = 1 if (j == 0 and etype == 3 and random.random() > 0.8) else None

            first, surname = make_name(random)
            draft_elements.append({
                "id": pid,
                "code": 100000 + pid,
                "element_type": etype,
                "team": t_idx,
                "web_name": surname,
                "first_name": first,
                "second_name": surname,
                "draft_rank": None,          # filled in below
                "ep_next": str(round(quality * 6.5, 1)),
                "status": status,
                "chance_of_playing_next_round": chance,
                "news": "Knee injury - expected back mid-September" if status == "i" else "",
                "penalties_order": pens,
                "corners_and_indirect_freekicks_order": corners,
                "direct_freekicks_order": fks,
                "total_points": 0,           # preseason: all counting stats reset
                "form": "0.0",
                "minutes": 0,
                "points_per_game": "0.0",
            })
            classic_elements.append({
                "id": pid,
                "code": 100000 + pid,
                "element_type": etype,
                "team": t_idx,
                "web_name": surname,
                "now_cost": int(price * 10),
                "ep_next": str(round(quality * 6.5, 1)),
                "selected_by_percent": str(round(quality * 40, 1)),
            })

            # Last season history for about 70% of players (the rest are new
            # signings or promoted-club players with no top-flight record).
            if random.random() > 0.30:
                mins = int(random.uniform(300, 3200) * depth)
                ppg = quality * random.uniform(3.0, 6.0)
                # Defensive contribution: 2 pts per qualifying match. Defenders
                # clear the bar most often, holding midfielders sometimes,
                # forwards almost never. Weaker teams defend more, so the rate
                # rises as team strength falls.
                hit = {1: 0.0, 2: 0.42, 3: 0.20, 4: 0.04}[etype]
                hit *= (1.6 - strength)
                apps = mins / 90.0
                past[str(pid)] = [{
                    "season_name": "2025/26",
                    "total_points": int(ppg * (mins / 90.0)),
                    "minutes": mins,
                    "defensive_contribution": round(
                        2.0 * apps * min(0.95, max(0.0, hit
                                                   * random.uniform(0.5, 1.5))), 1),
                }]

# draft_rank mirrors FPL's own preseason ordering, i.e. roughly by price.
for rank, e in enumerate(
        sorted(draft_elements,
               key=lambda d: next(c["now_cost"] for c in classic_elements
                                  if c["id"] == d["id"]),
               reverse=True), start=1):
    e["draft_rank"] = rank

# Upcoming fixtures with FPL-style difficulty, so the next-5 strip has data.
fixtures = []
for gw in range(1, 9):
    order = list(range(1, len(TEAMS) + 1))
    for i in range(0, len(order), 2):
        h, a = order[i], order[(i + 1) % len(order)]
        h = ((h + gw) % len(TEAMS)) + 1
        a = ((a + gw * 3) % len(TEAMS)) + 1
        if h == a:
            continue
        fixtures.append({"event": gw, "finished": False,
                         "kickoff_time": f"2026-08-{20+gw:02d}T14:00:00Z",
                         "team_h": h, "team_a": a,
                         "team_h_difficulty": 1 + (h + gw) % 5,
                         "team_a_difficulty": 1 + (a + gw * 2) % 5})

snapshot = {
    # Explicit marker so the exporters can warn loudly that this is not
    # real data. Names look plausible now, which makes that warning matter more.
    "sample": True,
    "fetched_at": 0,
    "game": {"current_event": None, "next_event": 1},
    "draft": {
        "elements": draft_elements,
        "element_types": ELEMENT_TYPES,
        "teams": [{"id": i, "name": n, "short_name": s}
                  for i, (n, s) in enumerate(TEAMS, start=1)],
    },
    "classic": {"elements": classic_elements},
    "past": past,
    "fixtures": fixtures,
}

with open("mock_snapshot.json", "w", encoding="utf-8") as fh:
    json.dump(snapshot, fh)

print(f"wrote mock_snapshot.json: {len(draft_elements)} players, "
      f"{len(past)} with history")
