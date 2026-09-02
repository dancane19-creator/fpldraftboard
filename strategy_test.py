"""Paired strategy comparison.

Methodology note, because the obvious version of this test is wrong: you cannot
seat strategy A at slot 2 and strategy B at slot 7 and compare them, because
draft slots are not equally good. Any difference you measure is contaminated by
slot advantage. Here the SAME slot is replayed with the same seed and the same
rivals, changing only the strategy, and results are averaged over every slot.

Strategies compared:
  naive   take the highest projected points available
  vorp    take the highest VORP available
  tilted  take the highest (vorp + LOOKAHEAD * opportunity-cost gain)

Rivals either follow the published FPL ordering (ADP), which is what casual
league-mates do, or value players themselves (VORP), which is the hard case.
"""
import random
from itertools import product

from fpl_data import load_snapshot
from model import SQUAD_LIMITS, build_players, compute_vorp, project
from strategy import (LOOKAHEAD, ROUNDS, expected_best_next, picks_until_next,
                      survival_probs)

snap = load_snapshot("mock_snapshot.json")
POS = ["GKP", "DEF", "MID", "FWD"]


def best_xi(sq):
    """You start 11 of 15 in a legal formation, so score that, not the squad."""
    by = {}
    for p in sq:
        by.setdefault(p.pos, []).append(p)
    for k in by:
        by[k].sort(key=lambda p: p.proj, reverse=True)
    best = 0.0
    for d, m, f in product(range(3, 6), range(2, 6), range(1, 4)):
        if d + m + f != 10:
            continue
        if (len(by.get("DEF", [])) < d or len(by.get("MID", [])) < m
                or len(by.get("FWD", [])) < f or not by.get("GKP")):
            continue
        best = max(best, by["GKP"][0].proj
                   + sum(p.proj for p in by["DEF"][:d])
                   + sum(p.proj for p in by["MID"][:m])
                   + sum(p.proj for p in by["FWD"][:f]))
    return best


def run(seed, strat, slot, rivals, n_teams=10):
    random.seed(seed)
    players = build_players(snap)
    project(players)
    taken, squads = set(), {s: [] for s in range(1, n_teams + 1)}

    order = []
    for r in range(ROUNDS):
        seats = list(range(1, n_teams + 1))
        if r % 2:
            seats.reverse()
        order += seats

    def need(seat):
        c = {}
        for p in squads[seat]:
            c[p.pos] = c.get(p.pos, 0) + 1
        return {pos: SQUAD_LIMITS[pos] - c.get(pos, 0) for pos in POS}

    for pick_no, seat in enumerate(order):
        avail = [p for p in players if p.draft_id not in taken]
        compute_vorp(players, n_teams, avail)
        n = need(seat)
        elig = [p for p in avail if n[p.pos] > 0]
        if not elig:
            continue

        if seat == slot:
            if strat == "naive":
                pick = max(elig, key=lambda p: p.proj)
            elif strat == "vorp":
                pick = max(elig, key=lambda p: p.vorp)
            else:
                _, _, gap = picks_until_next(slot, n_teams, pick_no)
                surv = survival_probs(avail, gap)
                en = {pos: expected_best_next(avail, surv, pos) for pos in POS}
                pick = max(elig, key=lambda p: p.vorp
                           + LOOKAHEAD * (p.vorp - en[p.pos]))
        elif rivals == "adp":
            pool = sorted(elig, key=lambda p: (p.draft_rank is None,
                                               p.draft_rank or 10 ** 6))
            pick = random.choice(pool[:4])
        else:
            pick = random.choice(sorted(elig, key=lambda p: p.vorp,
                                        reverse=True)[:5])
        taken.add(pick.draft_id)
        squads[seat].append(pick)
    return best_xi(squads[slot])


SLOTS, SEEDS = range(1, 11), range(10)

for rivals in ("adp", "vorp"):
    print(f"--- rivals draft by {rivals.upper()} "
          f"| paired, {len(list(SLOTS))} slots x {len(list(SEEDS))} seeds ---")
    base = {(s, d): run(d, "vorp", s, rivals) for s in SLOTS for d in SEEDS}
    for strat in ("naive", "tilted"):
        diffs = [run(d, strat, s, rivals) - base[(s, d)]
                 for s in SLOTS for d in SEEDS]
        moved = [x for x in diffs if x != 0]
        wins = sum(1 for x in moved if x > 0)
        label = f"{strat} vs plain VORP"
        print(f"  {label:<22} mean {sum(diffs)/len(diffs):+7.1f} XI pts  "
              f"| better in {wins}/{len(moved)} drafts where it differed")
    print()
print(f"LOOKAHEAD is currently {LOOKAHEAD}. Raising it toward 1.0 makes the")
print("tilt stronger and, in testing, steadily worse. See strategy.py.")
