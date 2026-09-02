"""Simulate a full 8-team x 15-round draft to shake out edge cases."""
import random, json, os
from fpl_data import load_snapshot
from model import build_players, project, compute_vorp, SQUAD_LIMITS
import draft as D

random.seed(1)
if os.path.exists(D.STATE_FILE): os.remove(D.STATE_FILE)

snap = load_snapshot("mock_snapshot.json")
players = build_players(snap); project(players)
state = {"n_teams": 8, "gone": [], "mine": [], "log": []}
by_id = {p.draft_id: p for p in players}

N_TEAMS, ROUNDS, MY_SLOT = 8, 15, 3
order = []
for r in range(ROUNDS):                       # snake draft
    seats = list(range(N_TEAMS))
    if r % 2: seats.reverse()
    order += seats

for pick_no, seat in enumerate(order):
    gone = set(state["gone"]) | set(state["mine"])
    compute_vorp(players, N_TEAMS, [p for p in players if p.draft_id not in gone])
    avail = [p for p in players if p.draft_id not in gone]
    assert avail, f"board empty at pick {pick_no}"
    if seat == MY_SLOT:
        needs = D.positional_needs(players, state)
        elig = [p for p in avail if needs.get(p.pos, 0) > 0]
        assert elig, f"no legal pick for me at {pick_no}"
        pick = max(elig, key=lambda p: p.vorp)
        state["mine"].append(pick.draft_id)
    else:
        # Opponents take near the top of the board with some noise.
        pick = random.choice(sorted(avail, key=lambda p: p.vorp, reverse=True)[:6])
        state["gone"].append(pick.draft_id)
    state["log"].append({"id": pick.draft_id, "mine": seat == MY_SLOT, "name": pick.name})

mine = [by_id[i] for i in state["mine"]]
counts = {}
for p in mine: counts[p.pos] = counts.get(p.pos, 0) + 1
print(f"picks made: {len(order)}  my squad: {len(mine)}")
print("my positions:", counts)
print("squad limits:", SQUAD_LIMITS)
assert len(mine) == ROUNDS, "wrong squad size"
for pos, lim in SQUAD_LIMITS.items():
    assert counts.get(pos, 0) <= lim, f"over limit at {pos}"
assert len(set(state["mine"]) & set(state["gone"])) == 0, "player double-drafted"
assert len(state["gone"]) + len(state["mine"]) == len(order), "pick count mismatch"
print(f"projected squad points: {sum(p.proj for p in mine):.0f}")
print("\nALL ASSERTIONS PASSED")
