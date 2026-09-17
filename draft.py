#!/usr/bin/env python3
"""
FPL Draft board - live best-available assistant.

QUICK START
-----------
    python3 draft.py fetch --deep      # once, before the draft (~2 min)
    python3 draft.py board             # the big board, ranked by VORP
    python3 draft.py best              # what should I take right now?
    python3 draft.py gone haaland      # someone else drafted him
    python3 draft.py mine saka         # I drafted him
    python3 draft.py roster            # my squad + what I still need
    python3 draft.py undo              # take back the last entry

You do NOT need a league ID for any of this. See README.md.

Interactive mode is easier during a live draft:

    python3 draft.py live

then just type names as picks happen: `saka` marks him gone, `+saka` marks him
as yours, `b` reprints the best available, `r` shows your roster.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from fpl_data import fetch_all, load_snapshot
from model import (SQUAD_LIMITS, TYPICAL_STARTERS, Player, build_players,
                   compute_vorp, project, replacement_levels, _norm_name)

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "draft_state.json")

POS_ORDER = ["GKP", "DEF", "MID", "FWD"]


# ---------------------------------------------------------------- state ----

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"n_teams": 8, "slot": 1, "gone": [], "mine": [], "log": []}


def save_state(st: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=2)


# ---------------------------------------------------------------- lookup ---

def find_player(players: list[Player], query: str) -> list[Player]:
    """Fuzzy-ish lookup: exact web name, then prefix, then substring."""
    q = _norm_name(query)
    if not q:
        return []
    exact = [p for p in players if _norm_name(p.name) == q]
    if exact:
        return exact
    pref = [p for p in players if any(k.startswith(q) for k in p.search_keys)]
    if pref:
        return pref
    return [p for p in players if any(q in k for k in p.search_keys)]


def resolve(players: list[Player], query: str) -> Player | None:
    hits = find_player(players, query)
    if not hits:
        print(f"  no match for '{query}'")
        return None
    if len(hits) == 1:
        return hits[0]
    # Prefer the most valuable match, but show the alternatives.
    hits.sort(key=lambda p: p.proj, reverse=True)
    print(f"  '{query}' matched {len(hits)}: " +
          ", ".join(f"{p.name} ({p.team_short})" for p in hits[:6]))
    print(f"  using {hits[0].name} ({hits[0].team_short}). "
          f"Use the fuller name if that is wrong.")
    return hits[0]


# ---------------------------------------------------------------- display --

def fmt_row(rank: int, p: Player, show_vorp: bool = True) -> str:
    flags = " ".join(f"[{f}]" for f in p.flags[:3])
    vorp = f"{p.vorp:+6.1f}" if show_vorp else "      "
    return (f"{rank:>3}. {p.name:<16.16} {p.pos:<3} {p.team_short:<3} "
            f"proj {p.proj:5.0f}  vorp {vorp}  t{p.tier} {flags}")


def print_board(players: list[Player], state: dict, limit: int,
                pos_filter: str | None) -> None:
    gone = set(state["gone"]) | set(state["mine"])
    avail = [p for p in players if p.draft_id not in gone]
    if pos_filter:
        avail = [p for p in avail if p.pos == pos_filter.upper()]
    avail.sort(key=lambda p: p.vorp, reverse=True)

    head = f"BIG BOARD - best available{f' ({pos_filter.upper()})' if pos_filter else ''}"
    print(f"\n{head}   [{len(avail)} left on the board]")
    print("-" * 74)
    last_tier = None
    for i, p in enumerate(avail[:limit], 1):
        if pos_filter and p.tier != last_tier:
            if last_tier is not None:
                print(f"     --- tier {p.tier} ---")
            last_tier = p.tier
        print(fmt_row(i, p))


def print_roster(players: list[Player], state: dict) -> None:
    by_id = {p.draft_id: p for p in players}
    mine = [by_id[i] for i in state["mine"] if i in by_id]
    counts = {pos: 0 for pos in POS_ORDER}
    for p in mine:
        counts[p.pos] = counts.get(p.pos, 0) + 1

    print(f"\nMY SQUAD ({len(mine)}/15)")
    print("-" * 74)
    for pos in POS_ORDER:
        group = [p for p in mine if p.pos == pos]
        need = SQUAD_LIMITS[pos] - counts.get(pos, 0)
        names = ", ".join(f"{p.name} ({p.team_short})" for p in group) or "-"
        print(f"  {pos} {counts.get(pos,0)}/{SQUAD_LIMITS[pos]}"
              f"{'  NEED ' + str(need) if need > 0 else '  full '}  {names}")
    total = sum(p.proj for p in mine)
    print(f"\n  projected squad points: {total:.0f}")


def positional_needs(players: list[Player], state: dict) -> dict[str, int]:
    by_id = {p.draft_id: p for p in players}
    mine = [by_id[i] for i in state["mine"] if i in by_id]
    counts = {pos: 0 for pos in POS_ORDER}
    for p in mine:
        counts[p.pos] = counts.get(p.pos, 0) + 1
    return {pos: SQUAD_LIMITS[pos] - counts.get(pos, 0) for pos in POS_ORDER}


def print_best(players: list[Player], state: dict, picks_until_next: int = 0,
               limit: int = 12) -> None:
    """The recommendation, driven by strategy.recommend.

    Sorted by VORP tilted toward positional scarcity, with the market's own
    ordering and a survival estimate shown so you can overrule it.
    """
    from strategy import recommend, explain

    gone = set(state["gone"])
    mine = set(state["mine"])
    slot = state.get("slot", 1)
    r = recommend(players, gone, mine, slot, state["n_teams"], top_n=limit)

    if not r["picks"]:
        print("\n  squad is full.")
        return

    print(f"\nROUND {r['round']}  |  your pick #{r['next']}  |  "
          f"next turn #{r.get('following', 0)}  |  {r['gap']} picks in between")
    print("-" * 78)
    print(f"{'':4}{'player':<16}{'pos':<5}{'tm':<5}{'proj':>5}{'vorp':>8}"
          f"{'lasts':>7}{'mkt':>6}")
    for i, e in enumerate(r["picks"], 1):
        p = e["p"]
        adp = p.draft_rank if p.draft_rank else "-"
        print(f"{i:>3}.{p.name:<16.16}{p.pos:<5}{p.team_short:<5}"
              f"{p.proj:>5.0f}{p.vorp:>+8.1f}{e['survive'] * 100:>6.0f}%{adp:>6}")
        why = explain(e, r["needs"])
        if why:
            print(f"     {'; '.join(why[:3])}")

    top = r["picks"][0]["p"]
    print(f"\n  >> TAKE: {top.name} ({top.pos}, {top.team_short})")
    if top.news:
        print(f"     note: {top.news}")


def print_scarcity(players: list[Player], state: dict, n_teams: int) -> None:
    gone = set(state["gone"]) | set(state["mine"])
    avail = [p for p in players if p.draft_id not in gone]
    print("\nPOSITIONAL SCARCITY")
    print("-" * 74)
    repl = replacement_levels(avail, n_teams)
    for pos in POS_ORDER:
        group = sorted([p for p in avail if p.pos == pos],
                       key=lambda x: x.proj, reverse=True)
        starters = int(round(TYPICAL_STARTERS[pos] * n_teams))
        above = sum(1 for p in group if p.proj > repl[pos] + 10)
        print(f"  {pos}: {len(group):>3} left | replacement {repl[pos]:5.0f} pts "
              f"| {above:>2} clearly above replacement | league needs ~{starters}")
    print("\n  Positions with few players above replacement are where you gain"
          "\n  the most by drafting early.")


# ---------------------------------------------------------------- engine ---

SAMPLE_DATA = False
SNAP: dict = {}


def prepare(args) -> tuple[list[Player], dict]:
    global SAMPLE_DATA, SNAP
    if getattr(args, "snapshot", None):
        snap = load_snapshot(args.snapshot)
    else:
        snap = fetch_all(deep=getattr(args, "deep", False),
                         use_cache=not getattr(args, "refresh", False))

    SAMPLE_DATA = bool(snap.get("sample"))
    SNAP = snap

    players = build_players(snap)
    if not players:
        print("No players returned. The Draft game may not be open yet.")
        sys.exit(1)

    state = load_state()
    if getattr(args, "teams", None):
        state["n_teams"] = args.teams
        save_state(state)
    if getattr(args, "slot", None):
        state["slot"] = args.slot
        save_state(state)

    project(players)
    try:
        from sleepers import annotate
        annotate(players)
    except Exception:
        pass                       # editorial notes are optional, never fatal
    gone = set(state["gone"]) | set(state["mine"])
    avail = [p for p in players if p.draft_id not in gone]
    compute_vorp(players, state["n_teams"], available_only=avail)
    return players, state


def mark(players: list[Player], state: dict, query: str, is_mine: bool) -> None:
    p = resolve(players, query)
    if p is None:
        return
    if p.draft_id in state["gone"] or p.draft_id in state["mine"]:
        print(f"  {p.name} is already off the board")
        return
    (state["mine"] if is_mine else state["gone"]).append(p.draft_id)
    state["log"].append({"id": p.draft_id, "mine": is_mine, "name": p.name})
    save_state(state)
    tag = "MINE" if is_mine else "gone"
    print(f"  {tag}: {p.name} ({p.pos}, {p.team_short})  "
          f"proj {p.proj:.0f} vorp {p.vorp:+.1f}")


def undo(players: list[Player], state: dict) -> None:
    if not state["log"]:
        print("  nothing to undo")
        return
    last = state["log"].pop()
    key = "mine" if last["mine"] else "gone"
    if last["id"] in state[key]:
        state[key].remove(last["id"])
    save_state(state)
    print(f"  undid: {last['name']}")


def live_mode(players: list[Player], state: dict, picks_until_next: int) -> None:
    print(__doc__.split("Interactive mode")[0])
    print("LIVE MODE. Commands:")
    print("  <name>      mark that player as drafted by someone else")
    print("  +<name>     mark that player as drafted by YOU")
    print("  b           best available recommendation")
    print("  board [POS] big board, optionally filtered (GKP/DEF/MID/FWD)")
    print("  r           my roster")
    print("  s           positional scarcity")
    print("  u           undo last")
    print("  q           quit\n")
    print_best(players, state, picks_until_next)

    while True:
        try:
            raw = input("\ndraft> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not raw:
            continue
        low = raw.lower()
        if low in ("q", "quit", "exit"):
            return
        if low == "b":
            recompute(players, state)
            print_best(players, state, picks_until_next)
        elif low.startswith("board"):
            parts = raw.split()
            recompute(players, state)
            print_board(players, state, 30,
                        parts[1] if len(parts) > 1 else None)
        elif low == "r":
            print_roster(players, state)
        elif low == "s":
            recompute(players, state)
            print_scarcity(players, state, state["n_teams"])
        elif low == "u":
            undo(players, state)
            recompute(players, state)
        elif raw.startswith("+"):
            mark(players, state, raw[1:], True)
            recompute(players, state)
            print_best(players, state, picks_until_next)
        else:
            mark(players, state, raw, False)


def recompute(players: list[Player], state: dict) -> None:
    gone = set(state["gone"]) | set(state["mine"])
    avail = [p for p in players if p.draft_id not in gone]
    compute_vorp(players, state["n_teams"], available_only=avail)


# ------------------------------------------------------------------ main ---

def _add_common(p) -> None:
    """Flags that are accepted both before and after the subcommand.

    argparse normally forces global options to come first, which is easy to get
    wrong under time pressure. Registering them on every subparser too means
    `draft.py fetch --deep` and `draft.py --deep fetch` both work.
    """
    p.add_argument("--snapshot", help="load a saved JSON snapshot instead of the API")
    p.add_argument("--teams", type=int, help="managers in your league (default 8)")
    p.add_argument("--slot", type=int,
                   help="your pick number in round 1 of the snake (default 1)")
    p.add_argument("--refresh", action="store_true", help="ignore the cache")
    p.add_argument("--deep", action="store_true",
                   help="also pull last season's history (slower, better)")


def main() -> None:
    ap = argparse.ArgumentParser(description="FPL Draft best-available board")
    _add_common(ap)
    sub = ap.add_subparsers(dest="cmd")

    def new(name, **kw):
        p = sub.add_parser(name, **kw)
        _add_common(p)
        return p

    new("fetch", help="download and cache the data")
    ex = new("export", help="write a self-contained HTML draft board")
    ex.add_argument("-o", "--out", default="draft-board.html")
    xl = new("export-xlsx", help="write an Excel draft board")
    xl.add_argument("-o", "--out", default="draft-board.xlsx")
    wv = new("waivers", help="in-season waiver targets, live from your league")
    wv.add_argument("--league", type=int, help="your league ID")
    wv.add_argument("--entry", type=int, help="your entry id")
    wv.add_argument("--port", type=int, default=8787)
    wv.add_argument("--no-open", action="store_true")
    wv.add_argument("--report", action="store_true",
                    help="print the list to the terminal and exit, no server")
    wv.add_argument("--dump", metavar="FILE", nargs="?", const="waiver-data.csv",
                    help="write every free agent and your squad to a small CSV "
                         "you can attach to a chat, then exit")
    mb = new("mobile", help="waiver board for your phone, served over home Wi-Fi")
    mb.add_argument("--league", type=int, help="your league ID")
    mb.add_argument("--entry", type=int, help="your entry id")
    mb.add_argument("--port", type=int, default=8797)
    mb.add_argument("--no-open", action="store_true",
                    help="do not open the QR page on this PC")
    mb.add_argument("--local", action="store_true",
                    help="localhost only, no Wi-Fi access (for testing)")
    pb = new("publish", help="write the phone board as a static site "
                             "(what the GitHub workflow runs)")
    pb.add_argument("--league", type=int, help="your league ID (or env FPL_LEAGUE)")
    pb.add_argument("--entry", type=int, help="your entry id (or env FPL_ENTRY)")
    pb.add_argument("-o", "--out", default="site", help="output folder")
    pb.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""),
                    help="owner/name, for the 'Run now' link on the page")
    sv = new("serve", help="live dashboard that follows your league")
    sv.add_argument("--league", type=int, help="your league ID")
    sv.add_argument("--entry", type=int, help="your entry id")
    sv.add_argument("--port", type=int, default=8777)
    sv.add_argument("--no-open", action="store_true", help="do not open a browser")
    sy = new("sync", help="pull live picks from your FPL Draft league")
    sy.add_argument("--league", type=int, help="your league ID")
    sy.add_argument("--entry", type=int, help="your entry id (see 'whoami')")
    who = new("whoami", help="list the managers in your league")
    who.add_argument("--league", type=int, help="your league ID")
    b = new("board", help="show the big board")
    b.add_argument("pos", nargs="?", help="GKP / DEF / MID / FWD")
    b.add_argument("-n", type=int, default=40)
    be = new("best", help="recommend a pick")
    be.add_argument("--until-next", type=int, default=14,
                    help="picks until your next turn (default 14)")
    g = new("gone", help="mark a player drafted by someone else")
    g.add_argument("name", nargs="+")
    m = new("mine", help="mark a player drafted by you")
    m.add_argument("name", nargs="+")
    new("roster", help="show my squad")
    new("scarcity", help="show positional scarcity")
    new("undo", help="undo the last entry")
    new("reset", help="clear all draft state")
    lv = new("live", help="interactive draft mode")
    lv.add_argument("--until-next", type=int, default=14)

    # argparse lets a subparser's defaults overwrite values the parent already
    # parsed, so a flag given *before* the subcommand gets wiped out. Scan for
    # the common flags with a standalone parser that has no subcommands, which
    # picks them up from anywhere in the command line, then fill in whatever
    # the main parse left empty.
    pre_ap = argparse.ArgumentParser(add_help=False)
    _add_common(pre_ap)
    pre, _ = pre_ap.parse_known_args()

    args = ap.parse_args()
    for flag in ("snapshot", "teams", "refresh", "deep", "slot"):
        if not getattr(args, flag, None) and getattr(pre, flag, None):
            setattr(args, flag, getattr(pre, flag))

    cmd = args.cmd or "best"

    if cmd == "reset":
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        print("  draft state cleared")
        return

    players, state = prepare(args)

    if cmd == "fetch":
        n_hist = sum(1 for p in players if p.last_season_pts is not None)
        print(f"  cached {len(players)} players. {n_hist} have last-season history.")
        if n_hist < len(players) * 0.4:
            print()
            print("  WARNING: almost nothing has last-season data, so every")
            print("  projection is running on price and draft rank alone.")
            print("  Fix it with:   py draft.py --deep --refresh fetch")
        print_scarcity(players, state, state["n_teams"])
    elif cmd == "waivers":
        import sync as sync_mod
        from season import enrich, is_in_season, current_event
        from waivers import build as build_waivers

        league = args.league or state.get("league")
        if not league:
            print("  Need a league ID:  py draft.py waivers --league 721 --entry 2438")
            return
        state["league"] = league
        if args.entry:
            state["entry"] = args.entry
        save_state(state)

        if not is_in_season(SNAP):
            print("  The season has not started, so there is nothing to claim.")
            print("  Use `serve` for the draft board instead.")
            return

        gw = current_event(SNAP)
        enrich(players, SNAP)

        my_ids: set[int] = set()
        owned: set[int] = set()
        mine_now: set[int] = set()
        try:
            entries = sync_mod.league_entries(league)
            chosen = state.get("entry")
            if not chosen:
                print("  Which entry is you? Re-run with --entry <number>:")
                for e in entries:
                    print(f"    --entry {e['entry_id']:<8} {e['team']:<26} {e['manager']}")
                return
            my_ids = sync_mod.my_id_set(entries, chosen)
            _, owners = sync_mod.draft_picks(league)
            owned = set(owners)
            mine_now = {el for el, ow in owners.items() if ow in my_ids}
            who = next((e for e in entries
                        if chosen in (e["entry_id"], e["id"])), None)
            if who:
                print(f"\n  You are '{who['team']}' - {len(mine_now)} players owned")
        except RuntimeError as exc:
            print(f"  Could not reach the league: {exc}")
            print("  Serving anyway; the page retries on its own.")

        by_id = {p.draft_id: p for p in players}
        squad = [by_id[i] for i in mine_now if i in by_id]
        if squad:
            print(f"  GW{gw} played. Your squad, weakest first:")
            for p in sorted(squad, key=lambda x: x.proj_week)[:5]:
                print(f"    {p.name:<18}{p.pos}  {p.proj_week:>4.1f} pts/wk  "
                      f"{p.start_rate:.0%} start rate")

        if args.dump:
            # A compact CSV so the whole picture can travel somewhere the API
            # is not reachable. Small enough to attach to a message.
            import csv
            from season import waiver_targets
            tg = {t["p"].draft_id: t for t in
                  waiver_targets(players, owned, mine_now)}
            out = os.path.abspath(args.dump)
            with open(out, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["status", "name", "pos", "team", "pts_per_week",
                            "start_rate", "form", "season_pts", "minutes",
                            "starts", "def_actions_p90", "gain_vs_my_starter",
                            "next5_fdr", "news"])
                for p in sorted(players, key=lambda x: -x.proj_week):
                    if p.draft_id in mine_now:
                        st = "MINE"
                    elif p.draft_id in owned:
                        continue          # rivals' players are not claimable
                    else:
                        st = "FREE"
                    if st == "FREE" and p.proj_week <= 0 and p.season_minutes == 0:
                        continue          # skip the long tail of non-players
                    g = tg.get(p.draft_id)
                    w.writerow([st, p.name, p.pos, p.team_short,
                                f"{p.proj_week:.2f}", f"{p.start_rate:.2f}",
                                f"{p.form:.1f}", int(p.season_points),
                                int(p.season_minutes), int(p.season_starts),
                                f"{p.dc_p90:.1f}",
                                f"{g['gain']:.2f}" if g else "",
                                "-".join(str(d) for d in p.fdr[:5]),
                                (p.news or "")[:60]])
            n = sum(1 for _ in open(out, encoding="utf-8")) - 1
            size = os.path.getsize(out) / 1024
            print(f"\n  wrote {out}")
            print(f"  {n} rows, {size:.0f} KB. Attach it to a chat with Claude")
            print("  and ask for a read on your waiver claims.\n")
            return

        if args.report:
            from season import waiver_targets, drop_candidates
            tg = waiver_targets(players, owned, mine_now)
            print(f"\n  TOP WAIVER TARGETS  (gain = pts/week over your weakest starter)")
            print("  " + "-" * 74)
            print(f"  {'#':<3}{'player':<20}{'pos':<5}{'tm':<5}"
                  f"{'pts/wk':>7}{'start':>7}{'form':>6}{'gain':>7}")
            for i, t in enumerate(tg[:20], 1):
                p = t["p"]
                print(f"  {i:<3}{p.name:<20.20}{p.pos:<5}{p.team_short:<5}"
                      f"{p.proj_week:>7.1f}{p.start_rate:>6.0%}{p.form:>6.1f}"
                      f"{t['gain']:>+7.1f}")
            print(f"\n  YOUR SQUAD, weakest first")
            print("  " + "-" * 74)
            for p in drop_candidates(players, mine_now):
                print(f"  {p.name:<20.20}{p.pos:<5}{p.team_short:<5}"
                      f"{p.proj_week:>7.1f}{p.start_rate:>6.0%}{p.form:>6.1f}"
                      f"  {int(p.season_points)} pts")
            print("\n  Paste this back to Claude for a second opinion.\n")
            return

        html = build_waivers(players, my_ids, owned, mine_now, gw,
                             sample=SAMPLE_DATA)
        print("  Want it on your phone?  py draft.py mobile   (see README)")
        from serve import serve as run_server
        run_server(html, league, port=args.port, open_browser=not args.no_open,
                   banner="Waiver board")
    elif cmd in ("mobile", "publish"):
        import mobile as mobile_mod
        import sync as sync_mod
        from season import enrich, is_in_season, current_event

        def _env_int(name: str) -> int | None:
            v = os.environ.get(name, "").strip()
            return int(v) if v.isdigit() else None

        # Flags win, then the environment (how the GitHub workflow passes
        # them), then whatever was saved last time.
        league = args.league or _env_int("FPL_LEAGUE") or state.get("league")
        if not league:
            print(f"  Need a league ID:  py draft.py {cmd} --league 721 --entry 2438")
            return
        state["league"] = league
        entry = args.entry or _env_int("FPL_ENTRY")
        if entry:
            state["entry"] = entry
        save_state(state)
        chosen = state.get("entry")

        gw = current_event(SNAP)
        enrich(players, SNAP)

        if cmd == "publish":
            # Static site for GitHub Pages. Any failure here must fail the
            # job, so the previous good board stays up rather than being
            # replaced by an error page.
            from fpl_data import _get_json
            if not chosen:
                print("  Need your entry id: py draft.py publish --entry <n> "
                      "(or set FPL_ENTRY). List them: py draft.py whoami")
                sys.exit(2)
            details = _get_json(sync_mod.LEAGUE_DETAILS.format(league))
            entries = sync_mod.league_entries(league)
            my_ids = sync_mod.my_id_set(entries, chosen)
            _, owners = sync_mod.draft_picks(league)
            owned = set(owners)
            mine_now = {el for el, ow in owners.items() if ow in my_ids}
            if not mine_now:
                print(f"  Entry {chosen} owns no players in league {league}.")
                print("  Wrong entry id? Check:  py draft.py whoami")
                sys.exit(2)
            error = None if is_in_season(SNAP) else "season not started yet"
            payload = mobile_mod.build_payload(players, SNAP, my_ids, owned,
                                               mine_now, details, error)
            out = os.path.abspath(args.out)
            written = mobile_mod.write_site(payload, out, repo=args.repo)
            who = next((e for e in entries
                        if chosen in (e["entry_id"], e["id"])), None)
            print(f"  {who['team'] if who else chosen}: GW{gw} played, "
                  f"{len(payload['claims'])} free agents scored, "
                  f"XI {payload['xi']} pts/wk")
            print(f"  wrote {len(written)} files to {out}")
            return

        # mobile: serve over Wi-Fi from this PC.
        from waivers import build as build_waivers
        if not is_in_season(SNAP):
            print("  The season has not started, so there is nothing to claim.")
            return
        if not chosen:
            print("  Which entry is you? Re-run with --entry <number>:")
            try:
                for e in sync_mod.league_entries(league):
                    print(f"    --entry {e['entry_id']:<8} {e['team']:<26} {e['manager']}")
            except RuntimeError as exc:
                print(f"  (could not list the league: {exc})")
            return
        my_ids = {chosen}
        try:
            entries = sync_mod.league_entries(league)
            my_ids = sync_mod.my_id_set(entries, chosen)
            who = next((e for e in entries
                        if chosen in (e["entry_id"], e["id"])), None)
            if who:
                print(f"\n  You are '{who['team']}' - GW{gw} played")
        except RuntimeError as exc:
            print(f"  Could not reach the league yet: {exc}")
            print("  Serving anyway; the feed retries every 20s.")

        feed = mobile_mod.MobileFeed(players, SNAP, league, my_ids,
                                     reload=not getattr(args, "snapshot", None)
                                     ).start()
        desktop = build_waivers(players, my_ids, set(feed.owned), set(feed.mine),
                                gw, sample=SAMPLE_DATA)
        page = mobile_mod.render_page("/api/mobile", static=False)
        pages = {"/m": page, "/mobile": page, "/qr": mobile_mod.QR_PAGE}
        blobs = {"/icon.png": (mobile_mod.icon_png(), "image/png"),
                 "/manifest.webmanifest": (mobile_mod.manifest("/m").encode(),
                                           "application/manifest+json")}
        routes = {"/api/mobile": feed.payload_bytes}
        from serve import serve as run_server
        run_server(desktop, league, port=args.port, open_browser=not args.no_open,
                   lan=not args.local, pages=pages, blobs=blobs, routes=routes,
                   open_path="/qr", banner="Desktop waiver board")
    elif cmd == "serve":
        import sync as sync_mod
        from dashboard import build
        league = args.league or state.get("league")
        if not league:
            print("  Need a league ID:  py draft.py serve --league 721 --entry 2438")
            print("  Don't know it?     py find_league.py --console")
            return
        state["league"] = league
        if args.entry:
            state["entry"] = args.entry
        save_state(state)

        my_ids: set[int] = set()
        try:
            entries = sync_mod.league_entries(league)
            if entries:
                state["n_teams"] = len(entries)
                save_state(state)
            chosen = state.get("entry")
            if chosen:
                my_ids = sync_mod.my_id_set(entries, chosen)
                who = next((e for e in entries
                            if chosen in (e["entry_id"], e["id"])), None)
                if who:
                    print(f"\n  You are '{who['team']}' ({who['manager']})")
            else:
                print("\n  No entry id set, so the dashboard cannot tell which")
                print("  picks are yours. Pick yours and re-run:")
                for e in entries:
                    print(f"    --entry {e['entry_id']:<8} {e['team']:<26} {e['manager']}")
        except RuntimeError as exc:
            print(f"  Could not reach the league: {exc}")
            print("  Serving anyway; the page will retry on its own.")

        html = build(players, state["n_teams"], state.get("slot", 1),
                     live=True, my_ids=my_ids, sample=SAMPLE_DATA)
        from serve import serve as run_server
        run_server(html, league, port=args.port, open_browser=not args.no_open)
    elif cmd == "export":
        from dashboard import build
        n_hist = sum(1 for p in players if p.last_season_pts is not None)
        note = (f"{state['n_teams']}-manager league &middot; "
                f"{n_hist} players with last-season data")
        out = os.path.abspath(args.out)
        html = build(players, state["n_teams"], state.get("slot", 1),
                     live=False, my_ids=set(), sample=SAMPLE_DATA)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"  wrote {out}")
        print("  Open it in your browser. Nothing else needed from here.")
        if not n_hist:
            print("  NOTE: no last-season data, so projections lean on price"
                  " alone. Re-run with --deep for better numbers.")
    elif cmd == "export-xlsx":
        try:
            from export_xlsx import export_xlsx
        except ImportError:
            print("  Excel export needs openpyxl. Install it with:")
            print("    py -m pip install openpyxl")
            return
        out = os.path.abspath(args.out)
        export_xlsx(players, state["n_teams"], out)
        print(f"  wrote {out}")
        print("  Open it in Excel. Use the yellow Status dropdowns to mark picks.")
    elif cmd in ("sync", "whoami"):
        import sync as sync_mod
        league = args.league or state.get("league")
        if not league:
            print("  Need a league ID. Open your league at "
                  "draft.premierleague.com and copy the number from the URL:")
            print("    https://draft.premierleague.com/league/123456/standings")
            print("                                            ^^^^^^")
            print("  Then run:  py draft.py whoami --league 123456")
            return
        state["league"] = league
        save_state(state)

        try:
            entries = sync_mod.league_entries(league)
        except RuntimeError as exc:
            print(f"\n  Could not reach your league.\n  {exc}")
            print("\n  Check the league ID is right, and that you can open")
            print(f"    https://draft.premierleague.com/api/league/{league}/details")
            print("  in your browser. If that page loads but this does not,")
            print("  something local is blocking Python's network access.")
            return
        if cmd == "whoami":
            print(f"\n  {sync_mod.league_name(league)}  ({len(entries)} managers)")
            print("  " + "-" * 60)
            for e in entries:
                alt = f" (or {e['id']})" if e['id'] != e['entry_id'] else ""
                print(f"    entry {e['entry_id']}{alt:<10} {e['team']:<26} {e['manager']}")
            print("\n  Then:  py draft.py sync --league "
                  f"{league} --entry <your entry number>")
            print("  Either number works; sync matches both.")
            return

        my_entry = args.entry or state.get("entry")
        if not my_entry:
            print("  Which of these is you? Re-run with --entry <number>:")
            for e in entries:
                print(f"    entry {e['entry_id']:<8} {e['team']:<26} {e['manager']}")
            return
        state["entry"] = my_entry
        if not args.teams:
            state["n_teams"] = len(entries) or state["n_teams"]

        picks, owners = sync_mod.draft_picks(league)
        mine_ids = sync_mod.my_id_set(entries, my_entry)
        sync_mod.apply_to_state(state, picks, owners, mine_ids)
        save_state(state)

        by_id = {p.draft_id: p for p in players}
        print(f"\n  Synced {len(picks)} picks from {sync_mod.league_name(league)}")
        print(f"  {len(state['mine'])} yours, {len(state['gone'])} taken by others")
        if picks:
            print("\n  Last few picks:")
            for p in picks[-6:]:
                pl = by_id.get(p["element"])
                tag = "YOU" if p.get("entry") in mine_ids else p.get("entry_name") or ""
                label = pl.name if pl else (p["name"] or f"element {p['element']}")
                rd = f"R{p['round']}.{p['pick']}" if p.get("round") else "  -  "
                print(f"    {rd:<7} {label:<20} {tag}")
        recompute(players, state)
        print_best(players, state)
    elif cmd == "board":
        print_board(players, state, args.n, args.pos)
    elif cmd == "best":
        print_best(players, state, args.until_next)
    elif cmd == "gone":
        mark(players, state, " ".join(args.name), False)
    elif cmd == "mine":
        mark(players, state, " ".join(args.name), True)
        recompute(players, state)
        print_roster(players, state)
    elif cmd == "roster":
        print_roster(players, state)
    elif cmd == "scarcity":
        print_scarcity(players, state, state["n_teams"])
    elif cmd == "undo":
        undo(players, state)
    elif cmd == "live":
        live_mode(players, state, args.until_next)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Happens when output is piped into head/less. Not an error.
        try:
            sys.stdout.close()
        except Exception:
            pass
    except KeyboardInterrupt:
        print()
