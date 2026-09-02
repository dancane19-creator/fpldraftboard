"""Pull live draft picks straight from your FPL Draft league.

This turned out to be much easier than expected. Two endpoints carry everything
needed, and **neither requires a login**:

    https://draft.premierleague.com/api/league/{league_id}/details
        -> league_entries: every manager, with entry_id, entry_name and their
           real name. This is how you work out which team is yours.

    https://draft.premierleague.com/api/draft/{league_id}/choices
        -> choices: every pick made, in order, each with round, pick number,
           the element (player) taken and the entry (manager) who took it.
        -> element_status: current owner of every player, which is the
           authoritative view if picks get traded afterwards.

So the only thing you have to supply is the league ID, and the only reason that
was ever a problem is that it is not shown anywhere obvious in the UI. It is in
the address bar once you open your league:

    https://draft.premierleague.com/league/123456/standings
                                            ^^^^^^

Everything else this module does is bookkeeping.
"""

from __future__ import annotations

from fpl_data import _get_json

LEAGUE_DETAILS = "https://draft.premierleague.com/api/league/{}/details"
DRAFT_CHOICES = "https://draft.premierleague.com/api/draft/{}/choices"


def league_entries(league_id: int) -> list[dict]:
    """Every manager in the league, so you can identify which one is you."""
    data = _get_json(LEAGUE_DETAILS.format(league_id))
    out = []
    for e in data.get("league_entries", []):
        out.append({
            "entry_id": e.get("entry_id"),
            "id": e.get("id"),
            "team": e.get("entry_name") or "(unnamed)",
            "manager": f"{e.get('player_first_name', '')} "
                       f"{e.get('player_last_name', '')}".strip(),
            "waiver_pick": e.get("waiver_pick"),
        })
    return out


def league_name(league_id: int) -> str:
    data = _get_json(LEAGUE_DETAILS.format(league_id))
    return (data.get("league") or {}).get("name", f"league {league_id}")


def draft_picks(league_id: int) -> tuple[list[dict], dict[int, int]]:
    """Return (picks in order, {element_id: owner_entry_id}).

    `choices` is the draft as it happened. `element_status` is who owns each
    player right now, which can differ after trades or waivers, so both are
    returned and the caller decides which matters.
    """
    data = _get_json(DRAFT_CHOICES.format(league_id))

    picks = []
    for c in data.get("choices", []):
        picks.append({
            "round": c.get("round"),
            "pick": c.get("pick"),
            "index": c.get("index"),
            "element": c.get("element"),
            "entry": c.get("entry"),
            "entry_name": c.get("entry_name"),
            "name": f"{c.get('player_first_name', '')} "
                    f"{c.get('player_last_name', '')}".strip(),
            "was_auto": c.get("was_auto", False),
        })
    # Sort by the draft's own ordering when present, so the log reads in order.
    picks.sort(key=lambda p: (p.get("index") if p.get("index") is not None
                              else (p.get("round") or 0) * 1000
                              + (p.get("pick") or 0)))

    owners = {}
    for s in data.get("element_status", []):
        if s.get("owner") is not None:
            owners[s["element"]] = s["owner"]

    return picks, owners


def my_id_set(entries: list[dict], chosen: int) -> set[int]:
    """Every id that could refer to you, because the feed uses two.

    A league entry carries BOTH an `entry_id` (the team, used by
    /api/entry/<id>/public) and an `id` (the league membership). They are
    usually different numbers, and the draft `choices` feed references one
    while other endpoints reference the other. Rather than guess which, match
    against both for whichever entry you picked.
    """
    for e in entries:
        if chosen in (e.get("entry_id"), e.get("id")):
            return {i for i in (e.get("entry_id"), e.get("id")) if i is not None}
    return {chosen}


def apply_to_state(state: dict, picks: list[dict], owners: dict[int, int],
                   my_entry: int | set[int] | None) -> dict:
    """Rewrite draft state from the league's own record.

    The league is the source of truth here, so this replaces local state rather
    than merging: anything you tracked by hand that the league disagrees with
    was wrong.
    """
    mine_ids = ({my_entry} if isinstance(my_entry, int)
                else set(my_entry or ()))
    gone, mine, log = [], [], []

    for p in picks:
        el = p["element"]
        is_mine = p.get("entry") in mine_ids
        (mine if is_mine else gone).append(el)
        log.append({"id": el, "mine": is_mine, "name": p["name"],
                    "round": p.get("round"), "pick": p.get("pick")})

    # element_status catches anything choices missed, e.g. waiver adds.
    seen = set(gone) | set(mine)
    for el, owner in owners.items():
        if el in seen:
            continue
        is_mine = owner in mine_ids
        (mine if is_mine else gone).append(el)
        log.append({"id": el, "mine": is_mine, "name": "", "round": None,
                    "pick": None})

    state["gone"] = gone
    state["mine"] = mine
    state["log"] = log
    return state
