"""Phone dashboard: the waiver board, sized for an iPhone and served over Wi-Fi.

Why not a native app? Because the whole point of this project is that nothing
needs installing. The desktop pages already run from a tiny Python server on
your PC; this binds that server to your home network instead of just localhost,
adds a page laid out for a phone, and tells Safari to treat it like an app when
you add it to the home screen. No App Store, no Xcode, no account.

    py draft.py mobile --league 721 --entry 2438

The PC prints a http://192.168.x.x:8797/m address. Open it on the phone, hit
Share -> Add to Home Screen, and it lives next to your other apps.

What it does differently from the desktop waiver page:

  * One number per row. On a phone there is room for the name, why he is
    worth it, and the gain. Everything else is a tap away.
  * The server does the work. The page fetches /api/mobile, which is the whole
    board already scored, so the phone never sees 700 players or runs the
    model. Ownership is refreshed on the PC every 20 seconds.
  * It keeps the last board it saw. Open it on the train with the PC asleep
    and you still get the list from this morning, stamped with when.
  * Pins live on the phone. Pin a long shot at number one and it stays
    pinned across refreshes and reopens.

Limits, so nobody is surprised: the PC has to be on and running the command,
and the phone has to be on the same Wi-Fi. That is the price of not having a
server in the cloud. Tailscale or similar would lift the Wi-Fi restriction
without changing anything here.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from datetime import datetime, timezone

from fpl_data import _get_json, fetch_all
from model import SQUAD_LIMITS, Player, build_players, project
from season import current_event, enrich, waiver_targets
import sync as sync_mod

# Who you would actually field. Same shape as season.my_replacement uses.
STARTERS = {"GKP": 1, "DEF": 4, "MID": 4, "FWD": 2}
POS_ORDER = ["GKP", "DEF", "MID", "FWD"]

# 180x180 home-screen icon. iOS wants a PNG, not SVG, and it is 700 bytes.
ICON_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAIAAACyr5FlAAACkElEQVR42u3cMZKCQBBAUaGIPYlH8DDG"
    "xh7DmJijbrZl7QoKMjh0vxerW4vfZrAcmuP5dIBnWocAcSAOxIE4EAfiQByIA3EgDhAH4kAciANxIA7E"
    "gTgQB+IAcSAOxIE4EAfiQByIg2i6z1/iOtwcxzr1l7vJgdMK4kAcJFiQrrsIop6LA5MDcSAOxIE4EAfi"
    "QByIA3EgDhAH4kAciANxIA7EgTgQB+IAcSAOxIE4EAd1WH875LIdeTZRrnIYTQ7EgThItOZ4f/XgZmKV"
    "H1KTA3EgDqpec+zOxHk6+bcvnSbeeUzOSjpZvP+UbIl0spCIOEbLmHiznz7lOtyS9NFmLqO/3Kff5rEH"
    "JPn6rs1ZxsssXj44Qx9ttjJmZTH9xPB9tNnK+PAFU/XRKkMf2Rek615fuFqJeeG6978ljqrHRp7hETOO"
    "7T/KIYdH/MlR7iMefnj4PQeZ4nic8KU/3I+vH+/MYnIgDuZrjueThbrFuMmBOBAHpdWyHXLFa84tL2Vr"
    "+y9sh8RpZY3RVfpKauMpJQ7EsZVyw8NvSHd/Zon6F8VR70fc1gTDI+/YOCTf8WZs5I2j0B6CQjsexLH7"
    "PvKUcUj4G9LrcFuWyP8n+g1pzMXprESePtjWhOAXLy8TGXtAkh1viW7e0l/uYzdjceGaPY7f93XxstQ9"
    "wSQii8Rx/Hm/3YdUHKaCqxXEgTiIteawAS7MITU5EAfioOo1h68NvngY7XjDaQVxIA7EgTgQB+IAcSAO"
    "xIE4EAfiQByIA3EgDhAH4kAciANxIA7EgTiIyC0YMDkQB+JAHHxVczyfHAVMDsSBOBAH4kAciANxIA7E"
    "AeJAHIgDcSAOxIE4EAfiQBwgDsSBOBAH4kAciANxEMoPFS7TZjFvYZkAAAAASUVORK5CYII="
)


def icon_png() -> bytes:
    return base64.b64decode(ICON_PNG_B64)


# ------------------------------------------------------------- payload ---

def _row(p: Player) -> dict:
    """The fields the phone needs for one player, and nothing else."""
    # Preseason flags like "no PL history" explain a projection that no longer
    # exists once real matches are in; only availability and set pieces matter.
    flags = [f for f in p.flags if "history" not in f.lower()][:3]
    return {
        "i": p.draft_id, "n": p.name, "pos": p.pos, "tm": p.team_short,
        "pw": round(p.proj_week, 2), "sr": round(p.start_rate, 2),
        "fm": round(p.form, 1), "tp": int(p.season_points),
        "mn": int(p.season_minutes), "st": int(p.season_starts),
        "fdr": p.fdr[:5], "f": flags,
        "nw": (p.news or "")[:90],
        "s": f"{p.name} {p.full_name}".lower(),
    }


def _next_event(snap: dict, gw: int) -> dict:
    """The upcoming gameweek's record from bootstrap-static, if it is there.

    The Draft feed nests these under events.data with a `next` pointer, but the
    shape is not something to bet the page on, so every step is a .get and the
    page shows nothing rather than something wrong.
    """
    ev = (snap.get("draft") or {}).get("events") or {}
    data = ev.get("data") if isinstance(ev, dict) else ev
    if not isinstance(data, list):
        return {}
    nxt = (ev.get("next") if isinstance(ev, dict) else None) or (gw + 1)
    for e in data:
        if isinstance(e, dict) and e.get("id") == nxt:
            return e
    return {}


def build_payload(players: list[Player], snap: dict, my_ids: set[int],
                  owned: set[int], mine: set[int], league: dict | None,
                  error: str | None = None) -> dict:
    """Everything the phone page renders, already scored.

    `league` is the parsed /league/{id}/details response, or None if it could
    not be fetched, in which case ownership is whatever was last known.
    """
    gw = current_event(snap)
    by_id = {p.draft_id: p for p in players}
    squad = [by_id[i] for i in mine if i in by_id]

    # Your squad by position, best first, with the starter line drawn and the
    # weakest starter marked because that is who every claim is scored against.
    squad_rows, xi_total, repl_name = [], 0.0, {}
    for pos in POS_ORDER:
        g = sorted([p for p in squad if p.pos == pos],
                   key=lambda x: x.proj_week, reverse=True)
        n = min(STARTERS[pos], len(g))
        for k, p in enumerate(g):
            r = _row(p)
            r["starter"] = k < n
            r["repl"] = (k == n - 1)          # weakest starter at this position
            if r["starter"]:
                xi_total += p.proj_week
            if r["repl"]:
                repl_name[pos] = p.name
            squad_rows.append(r)
    drop_name = {}
    for pos in POS_ORDER:
        g = sorted([p for p in squad if p.pos == pos], key=lambda x: x.proj_week)
        if g:
            drop_name[pos] = g[0].name

    # Free agents, scored by season.waiver_targets so the phone and the
    # desktop page never disagree. All of them go over, sorted, so a pin on
    # someone outside the top of the list still has a row to attach to.
    claims = []
    if squad:
        for t in waiver_targets(players, owned, mine):
            p = t["p"]
            r = _row(p)
            r["gain"] = round(t["gain"], 2)
            r["over"] = repl_name.get(p.pos, "")
            r["repl_pw"] = round(t["replaces"], 2)
            r["drop"] = drop_name.get(p.pos, "")
            claims.append(r)

    # League header: your team, rank, points and the table.
    me, table, lg_name, n_teams = {}, [], "", 0
    if league:
        lg_name = (league.get("league") or {}).get("name", "")
        entries = league.get("league_entries") or []
        n_teams = len(entries)
        name_by_le = {e.get("id"): (e.get("entry_name") or "?") for e in entries}
        for s in league.get("standings") or []:
            le = s.get("league_entry")
            row = {"rank": s.get("rank"), "team": name_by_le.get(le, "?"),
                   "total": s.get("total"), "gw": s.get("event_total"),
                   "me": le in my_ids}
            table.append(row)
            if row["me"]:
                me = row
        table.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))
        who = next((e for e in entries
                    if e.get("id") in my_ids or e.get("entry_id") in my_ids), None)
        if who:
            me = dict(me, team=who.get("entry_name") or me.get("team", ""),
                      manager=f"{who.get('player_first_name', '')} "
                              f"{who.get('player_last_name', '')}".strip())

    nxt = _next_event(snap, gw)
    game = snap.get("game") or {}
    return {
        "built": time.time(),
        "data_age_h": round(float(snap.get("_cache_age_hours") or 0.0), 1),
        "sample": bool(snap.get("sample")),
        "error": error,
        "gw": gw,
        "next_gw": game.get("next_event") or nxt.get("id") or (gw + 1),
        "deadline": nxt.get("deadline_time"),
        "waivers_at": nxt.get("waivers_time"),
        "trades_at": nxt.get("trades_time"),
        "waivers_processed": game.get("waivers_processed"),
        "league": lg_name, "n_teams": n_teams, "me": me, "table": table,
        "limits": SQUAD_LIMITS, "starters": STARTERS,
        "xi": round(xi_total, 1),
        "squad": squad_rows,
        "claims": claims,
        "owned": len(owned),
    }


# ------------------------------------------------------------- feed ---

class MobileFeed:
    """Keeps a scored board ready so every phone request is instant.

    Ownership and standings are re-read from the league on a timer in a
    background thread, never inside a request, because a flaky network should
    make the page say "stale", not hang. Projections are rebuilt when the
    cached snapshot passes its age limit, which fetch_all already enforces.
    """

    OWNERSHIP_EVERY = 20.0          # seconds between league reads
    PROJECTION_EVERY = 6 * 3600.0   # matches fetch_all's cache age

    def __init__(self, players: list[Player], snap: dict, league_id: int,
                 my_ids: set[int], reload: bool = True):
        self.players = players
        self.snap = snap
        self.league_id = league_id
        self.my_ids = set(my_ids)
        self.reload = reload
        self.owned: set[int] = set()
        self.mine: set[int] = set()
        self.league: dict | None = None
        self.error: str | None = None
        self._payload: dict | None = None
        self._lock = threading.Lock()
        self._last_proj = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> "MobileFeed":
        # One synchronous league read so the first request is already right,
        # then everything else happens off the request path.
        try:
            self._read_league()
        except Exception as exc:            # noqa: BLE001
            self.error = f"league unreachable: {exc}"[:160]
        self._rebuild()
        self._thread.start()
        return self

    def payload_bytes(self) -> bytes:
        with self._lock:
            body = self._payload or {}
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    # -- internals --------------------------------------------------------

    def _read_league(self) -> None:
        details = _get_json(sync_mod.LEAGUE_DETAILS.format(self.league_id))
        _, owners = sync_mod.draft_picks(self.league_id)
        with self._lock:
            self.league = details
            self.owned = set(owners)
            self.mine = {el for el, ow in owners.items() if ow in self.my_ids}
            self.error = None

    def _refresh_projections(self) -> None:
        """Re-pull the snapshot if fetch_all thinks it is old, keep the depth."""
        deep = bool(self.snap.get("past"))
        snap = fetch_all(deep=deep, use_cache=True)
        if snap.get("fetched_at") == self.snap.get("fetched_at"):
            return                          # cache still fresh, nothing to do
        players = build_players(snap)
        project(players)
        enrich(players, snap)
        with self._lock:
            self.players, self.snap = players, snap

    def _rebuild(self) -> None:
        with self._lock:
            players, snap = self.players, self.snap
            my_ids, owned, mine = self.my_ids, set(self.owned), set(self.mine)
            league, error = self.league, self.error
        body = build_payload(players, snap, my_ids, owned, mine, league, error)
        with self._lock:
            self._payload = body

    def _loop(self) -> None:
        while True:
            try:
                self._read_league()
            except Exception as exc:        # noqa: BLE001
                with self._lock:
                    self.error = f"league unreachable: {exc}"[:160]
            if self.reload and time.time() - self._last_proj > self.PROJECTION_EVERY:
                try:
                    self._refresh_projections()
                except Exception:           # keep serving the old numbers
                    pass
                self._last_proj = time.time()
            try:
                self._rebuild()
            except Exception as exc:        # noqa: BLE001
                with self._lock:
                    self.error = f"build failed: {exc}"[:160]
            time.sleep(self.OWNERSHIP_EVERY)


# ------------------------------------------------------------- page ---

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Waivers">
<meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0e3c2c">
<link rel="apple-touch-icon" href="icon.png">
<link rel="manifest" href="manifest.webmanifest">
<title>Waivers</title>
<style>
  :root{color-scheme:light dark;
    --surface:#fcfcfb;--plane:#f2f2ef;--sunk:#e9e8e3;
    --ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
    --grid:#e1e0d9;--rule:#c3c2b7;--border:rgba(11,11,11,0.10);
    --accent:#2a78d6;--good:#0a8f0a;--warn:#c98a00;--crit:#d03b3b;
    --pin:#b8860b;--brand:#0e3c2c;--brand-ink:#d9f5e5}
  @media(prefers-color-scheme:dark){:root{
    --surface:#1c1c1b;--plane:#0d0d0d;--sunk:#262625;
    --ink:#fff;--ink-2:#c3c2b7;--muted:#8f8e88;
    --grid:#2c2c2a;--rule:#3a3a37;--border:rgba(255,255,255,0.10);
    --accent:#4a93ec;--good:#3ec13e;--warn:#f0b323;--crit:#ef6262;
    --pin:#f0b323}}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--plane);color:var(--ink);
    font:16px/1.4 -apple-system,system-ui,"Segoe UI",sans-serif;
    padding-bottom:calc(72px + env(safe-area-inset-bottom))}

  /* header, sits under the notch in home-screen mode */
  .hdr{background:var(--brand);color:var(--brand-ink);
    padding:calc(10px + env(safe-area-inset-top)) 16px 12px}
  .hdr .lg{font-size:20px;font-weight:700;letter-spacing:-.01em;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .hdr .sub{font-size:13px;opacity:.85;margin-top:2px;display:flex;gap:8px;
    align-items:center;flex-wrap:wrap}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block;
    background:#9aa;margin-right:5px;vertical-align:0}
  .live .dot{background:#4ade80;animation:pulse 2s infinite}
  .err .dot{background:#f87171}
  .stale .dot{background:#fbbf24}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

  .tiles{display:grid;grid-template-columns:1.2fr 1.2fr .8fr;gap:8px;
    padding:12px 16px 4px}
  .tile{background:var(--surface);border:1px solid var(--border);
    border-radius:12px;padding:9px 10px;min-width:0}
  .tile .k{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
    color:var(--muted);font-weight:700;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis}
  .tile .v{font-size:18px;font-weight:700;margin-top:2px;
    font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;letter-spacing:-.01em}
  .tile .s{font-size:11.5px;color:var(--ink-2);white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis}

  .banner{margin:10px 16px 0;padding:10px 12px;border-radius:10px;font-size:13.5px;
    background:color-mix(in srgb,var(--warn) 16%,transparent);
    border:1px solid var(--warn)}
  .banner.bad{background:color-mix(in srgb,var(--crit) 12%,transparent);
    border-color:var(--crit)}

  /* segmented control */
  .seg{display:flex;margin:12px 16px 8px;background:var(--sunk);
    border-radius:10px;padding:3px}
  .seg button{flex:1;border:0;background:transparent;color:var(--ink-2);
    font:600 14px/1 inherit;font-family:inherit;padding:9px 0;border-radius:8px}
  .seg button.on{background:var(--surface);color:var(--ink);
    box-shadow:0 1px 2px rgba(0,0,0,.12)}

  .chips{display:flex;gap:6px;padding:4px 16px 8px;overflow-x:auto;
    scrollbar-width:none}
  .chips::-webkit-scrollbar{display:none}
  .chips button{border:1px solid var(--rule);background:var(--surface);
    color:var(--ink-2);font:600 13px/1 inherit;font-family:inherit;
    padding:8px 13px;border-radius:20px;white-space:nowrap}
  .chips button.on{background:var(--ink);color:var(--plane);border-color:var(--ink)}
  .search{margin:0 16px 8px;display:flex;gap:6px}
  .search input{flex:1;font:16px inherit;font-family:inherit;padding:10px 12px;
    border-radius:10px;border:1px solid var(--rule);background:var(--surface);
    color:var(--ink);min-width:0}

  .card{background:var(--surface);border:1px solid var(--border);
    border-radius:14px;margin:0 16px 12px;overflow:hidden}
  .card h3{margin:0;padding:10px 14px 6px;font-size:10.5px;letter-spacing:.09em;
    text-transform:uppercase;color:var(--muted);font-weight:700}
  .card .hint{padding:0 14px 8px;font-size:12.5px;color:var(--muted)}

  /* claim rows */
  .row{display:grid;grid-template-columns:30px 1fr auto 44px;gap:8px;
    align-items:center;padding:10px 6px 10px 10px;border-top:1px solid var(--grid);
    min-height:56px}
  .row.pin{background:color-mix(in srgb,var(--pin) 12%,transparent)}
  .rank{font-size:17px;font-weight:700;color:var(--muted);text-align:center;
    font-variant-numeric:tabular-nums}
  .row.pin .rank{color:var(--pin)}
  .nm{font-weight:650;font-size:16px;line-height:1.2}
  .meta{font-size:12.5px;color:var(--ink-2);margin-top:3px}
  .why{font-size:12px;color:var(--muted);margin-top:2px}
  .why b{color:var(--ink-2);font-weight:600}
  .gain{text-align:right;font-variant-numeric:tabular-nums;padding-right:2px}
  .gain .g1{font-size:18px;font-weight:700}
  .gain .g2{font-size:10.5px;color:var(--muted)}
  .up{color:var(--good)}.down{color:var(--crit)}
  .star{border:0;background:transparent;font-size:22px;line-height:1;
    width:44px;height:44px;color:var(--rule);padding:0}
  .row.pin .star{color:var(--pin)}
  .st{font-variant-numeric:tabular-nums;font-weight:600}
  .st.hi{color:var(--good)}.st.mid{color:var(--warn)}.st.lo{color:var(--crit)}
  .flag{display:inline-block;font-size:10px;padding:0 5px;border-radius:4px;
    border:1px solid var(--border);color:var(--muted);margin-left:4px;
    vertical-align:1px}
  .flag.hurt{border-color:var(--crit);color:var(--crit);font-weight:700}
  .fdr{display:inline-flex;gap:2px;margin-left:6px;vertical-align:-2px}
  .fdr i{width:13px;height:13px;border-radius:3px;display:inline-flex;
    align-items:center;justify-content:center;font:700 9px/1 inherit;
    font-style:normal;color:#fff}
  .fdr .d1,.fdr .d2{background:#188a18}.fdr .d3{background:#8a8a84}
  .fdr .d4{background:#d9682e}.fdr .d5{background:#c92e2e}
  .more{display:none;grid-column:2/5;font-size:12.5px;color:var(--ink-2);
    padding:0 6px 4px 0}
  .row.open .more{display:block}
  .empty{padding:26px 14px;text-align:center;color:var(--muted)}

  /* squad */
  .poshead{display:flex;justify-content:space-between;padding:10px 14px 4px;
    font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
    color:var(--muted);font-weight:700;border-top:1px solid var(--grid)}
  .sq{display:grid;grid-template-columns:1fr auto;gap:10px;padding:8px 14px;
    align-items:center;border-top:1px solid var(--grid)}
  .sq.bench{opacity:.62}
  .sq.repl{background:color-mix(in srgb,var(--crit) 9%,transparent)}
  .sq .sn{font-weight:650}
  .sq .sm{font-size:12px;color:var(--ink-2)}
  .sq .sv{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums;
    text-align:right}
  .sq .sv small{display:block;font-size:10.5px;color:var(--muted);font-weight:500}
  .tag{font-size:10px;padding:1px 6px;border-radius:4px;margin-left:6px;
    background:var(--sunk);color:var(--ink-2);vertical-align:1px;font-weight:600}
  .tag.r{background:color-mix(in srgb,var(--crit) 18%,transparent);color:var(--crit)}

  /* table */
  table{width:100%;border-collapse:collapse;font-size:14.5px}
  td,th{padding:9px 12px;text-align:left;border-top:1px solid var(--grid)}
  th{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;
    color:var(--muted);border-top:0}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
  tr.me td{background:color-mix(in srgb,var(--accent) 12%,transparent);font-weight:650}

  .foot{position:fixed;left:0;right:0;bottom:0;display:flex;gap:10px;
    align-items:center;padding:10px 16px calc(10px + env(safe-area-inset-bottom));
    background:color-mix(in srgb,var(--plane) 88%,transparent);
    -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
    border-top:1px solid var(--grid);font-size:12.5px;color:var(--muted)}
  .foot .spacer{flex:1}
  .foot .gh{color:var(--accent);text-decoration:none;font-weight:600;
    padding:6px 4px}
  .foot button{font:600 14px inherit;font-family:inherit;padding:9px 16px;
    border-radius:10px;border:1px solid var(--rule);background:var(--surface);
    color:var(--ink)}
  [hidden]{display:none!important}
</style>
</head>
<body>
<div class="hdr">
  <div class="lg" id="lg">Waivers</div>
  <div class="sub"><span id="status" class="live"><span class="dot"></span><span id="statusTxt">connecting</span></span>
    <span id="teamLine"></span></div>
</div>

<div class="tiles">
  <div class="tile"><div class="k">Deadline</div><div class="v" id="dlV">-</div><div class="s" id="dlS"></div></div>
  <div class="tile"><div class="k">Waivers</div><div class="v" id="wvV">-</div><div class="s" id="wvS"></div></div>
  <div class="tile"><div class="k">Your XI</div><div class="v" id="xiV">-</div><div class="s">pts / wk</div></div>
</div>

<div id="banner" class="banner" hidden></div>

<div class="seg" id="tabs">
  <button data-t="claims" class="on">Claims</button>
  <button data-t="squad">Squad</button>
  <button data-t="league">League</button>
</div>

<section id="tab-claims">
  <div class="chips" id="chips"></div>
  <div class="search"><input id="q" placeholder="Search a free agent to pin" autocomplete="off" autocorrect="off" autocapitalize="off"></div>
  <div class="card">
    <h3>Claim order</h3>
    <div class="hint">Gain is points per week over your weakest <b>starter</b> at
      that position. A pinned long shot at #1 costs nothing: if he is gone the
      claim falls through. Tap a name for details, the star to pin.</div>
    <div id="claims"></div>
  </div>
</section>

<section id="tab-squad" hidden>
  <div class="card">
    <h3>Your squad <span id="sqCount"></span></h3>
    <div class="hint">Best first. Faded rows are bench. The red row is the
      weakest starter, which is who every claim is measured against.</div>
    <div id="squad"></div>
  </div>
</section>

<section id="tab-league" hidden>
  <div class="card">
    <h3>Standings</h3>
    <div id="table"></div>
  </div>
</section>

<div class="foot">
  <span id="upd">-</span>
  <a id="ghlink" class="gh" hidden target="_blank" rel="noopener">Run now</a>
  <span class="spacer"></span>
  <button id="refresh">Refresh</button>
</div>

<script>
/* Filled in by Python. On the PC server the page polls /api/mobile every 30s;
   published to GitHub Pages it reads data.json, which the workflow rewrites. */
const DATA_URL="__DATA_URL__", STATIC=__STATIC__, REPO="__REPO__";
const POS=["GKP","DEF","MID","FWD"];
let D=null, pinned=new Set(), posFilter=null, tab="claims", lastFetch=0;

/* Pins and the last board live on the phone. This is your own server on your
   own Wi-Fi, so there is nowhere else sensible for them to go. */
function loadLocal(){
  try{
    const p=JSON.parse(localStorage.getItem("fpl-pins")||"[]"); p.forEach(x=>pinned.add(x));
    const c=localStorage.getItem("fpl-mobile-cache"); if(c) D=JSON.parse(c);
  }catch(e){}
}
function savePins(){ try{ localStorage.setItem("fpl-pins",JSON.stringify([...pinned])); }catch(e){} }
function saveCache(){ try{ localStorage.setItem("fpl-mobile-cache",JSON.stringify(D)); }catch(e){} }

function esc(s){ return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function stCls(r){ return r>=0.85?"hi":r>=0.5?"mid":"lo"; }
function fdr(p){ return (p.fdr&&p.fdr.length)?`<span class="fdr" aria-label="next fixtures">`+
  p.fdr.map(d=>`<i class="d${d}">${d}</i>`).join("")+`</span>`:""; }
function flags(p){ return (p.f||[]).map(f=>{
  const hurt=/injur|doubt|suspend|unavail|fit|not in squad/.test(f);
  return `<span class="flag ${hurt?"hurt":""}">${esc(f)}</span>`; }).join(""); }
function ago(t){ const s=Math.max(0,(Date.now()/1000)-t);
  return s<60?`${Math.round(s)}s ago`:s<3600?`${Math.round(s/60)}m ago`:`${(s/3600).toFixed(1)}h ago`; }
/* "Sat 5am" / "Thu 6:30am": short enough for a phone tile, in local time. */
function when(iso){
  if(!iso) return ["-",""];
  const d=new Date(iso); if(isNaN(d)) return ["-",""];
  const wd=d.toLocaleString([], {weekday:"short"});
  let h=d.getHours(), m=d.getMinutes(); const ap=h>=12?"pm":"am"; h=h%12||12;
  const v=`${wd} ${h}${m?":"+String(m).padStart(2,"0"):""}${ap}`;
  const ms=d-Date.now(); if(ms<0) return [v,"passed"];
  const hrs=ms/36e5; const s=hrs>=48?`in ${Math.floor(hrs/24)}d ${Math.round(hrs%24)}h`:hrs>=1?`in ${Math.floor(hrs)}h ${Math.round((hrs%1)*60)}m`:`in ${Math.round(hrs*60)}m`;
  return [v,s];
}

function setStatus(k,t){ document.getElementById("status").className=k;
  document.getElementById("statusTxt").textContent=t; }

function render(){
  if(!D) return;
  document.getElementById("lg").textContent=D.league||"Waivers";
  const me=D.me||{};
  document.getElementById("teamLine").innerHTML = me.team
    ? `${esc(me.team)}${me.rank?` &middot; rank ${me.rank}/${D.n_teams||"?"}`:""}${me.total!=null?` &middot; ${me.total} pts`:""}`
    : "";
  const [dv,ds]=when(D.deadline);
  document.getElementById("dlV").textContent=dv;
  document.getElementById("dlS").textContent=`GW${D.next_gw||"?"}${ds?" · "+ds:""}`;
  const [wv,ws]=when(D.waivers_at); document.getElementById("wvV").textContent=wv;
  document.getElementById("wvS").textContent=D.waivers_processed?"processed":ws;
  document.getElementById("xiV").textContent=(D.xi!=null)?D.xi.toFixed(1):"-";

  const b=document.getElementById("banner");
  if(D.sample){ b.hidden=false; b.className="banner bad"; b.textContent="Sample data, not real players. Run: py draft.py --refresh fetch"; }
  else if(D.error){ b.hidden=false; b.className="banner"; b.textContent="League not reachable from the PC, ownership may be out of date. "+D.error; }
  else if(!D.squad||!D.squad.length){ b.hidden=false; b.className="banner"; b.textContent="No squad found for your entry. Check --entry with: py draft.py whoami"; }
  else b.hidden=true;

  renderClaims(); renderSquad(); renderTable();
  document.getElementById("upd").textContent=`board ${ago(D.built)} · data ${D.data_age_h}h old`;
}

function renderClaims(){
  let rows=(D.claims||[]).map(r=>({...r,pinned:pinned.has(r.i)}));
  if(posFilter) rows=rows.filter(r=>r.pos===posFilter);
  rows.sort((a,b)=>(b.pinned?1:0)-(a.pinned?1:0)||b.gain-a.gain);
  const top=rows.slice(0,25);
  const el=document.getElementById("claims");
  el.innerHTML = top.length ? top.map((r,i)=>`
    <div class="row ${r.pinned?"pin":""}" data-id="${r.i}">
      <div class="rank">${i+1}</div>
      <div class="main">
        <div class="nm">${esc(r.n)}</div>
        <div class="meta">${r.pos} &middot; ${esc(r.tm)} &middot;
          <span class="st ${stCls(r.sr)}">${Math.round(r.sr*100)}% start</span>
          &middot; ${r.pw.toFixed(1)}/wk ${flags(r)}${fdr(r)}</div>
        <div class="why">over <b>${esc(r.over||"nobody")}</b> ${r.repl_pw!=null?`(${r.repl_pw.toFixed(1)}/wk)`:""}${r.drop&&r.drop!==r.over?` &middot; drop <b>${esc(r.drop)}</b>`:""}</div>
      </div>
      <div class="gain"><div class="g1 ${r.gain>0?"up":"down"}">${r.gain>0?"+":""}${r.gain.toFixed(1)}</div><div class="g2">pts/wk</div></div>
      <button class="star" data-pin="${r.i}" aria-label="pin">${r.pinned?"★":"☆"}</button>
      <div class="more">form ${r.fm.toFixed(1)} &middot; ${r.tp} pts &middot; ${r.st} starts, ${r.mn} min this season${r.nw?`<br>${esc(r.nw)}`:""}</div>
    </div>`).join("") : `<div class="empty">No free agents match.</div>`;
}

function renderSquad(){
  const sq=D.squad||[]; let html="";
  for(const pos of POS){
    const g=sq.filter(p=>p.pos===pos);
    html+=`<div class="poshead"><span>${pos}</span><span>${g.length}/${(D.limits||{})[pos]||"-"}</span></div>`;
    if(!g.length){ html+=`<div class="sq"><span class="sm">none</span></div>`; continue; }
    for(const p of g){
      html+=`<div class="sq ${p.starter?"":"bench"} ${p.repl?"repl":""}">
        <div><div class="sn">${esc(p.n)}${p.repl?`<span class="tag r">claims beat this</span>`:p.starter?"":`<span class="tag">bench</span>`}</div>
          <div class="sm">${esc(p.tm)} &middot; <span class="st ${stCls(p.sr)}">${Math.round(p.sr*100)}% start</span> &middot; form ${p.fm.toFixed(1)} ${flags(p)}${fdr(p)}</div></div>
        <div class="sv">${p.pw.toFixed(1)}<small>${p.tp} pts</small></div>
      </div>`;
    }
  }
  document.getElementById("squad").innerHTML=html;
  document.getElementById("sqCount").textContent=sq.length?`${sq.length}/15`:"";
}

function renderTable(){
  const t=D.table||[];
  document.getElementById("table").innerHTML = t.length ? `<table>
    <tr><th>#</th><th>Team</th><th class="n">GW</th><th class="n">Total</th></tr>
    ${t.map(r=>`<tr class="${r.me?"me":""}"><td>${r.rank??"-"}</td><td>${esc(r.team)}</td><td class="n">${r.gw??"-"}</td><td class="n">${r.total??"-"}</td></tr>`).join("")}
  </table>` : `<div class="empty">Standings not loaded yet.</div>`;
}

document.addEventListener("click",e=>{
  const pin=e.target.closest("[data-pin]");
  if(pin){ const id=+pin.dataset.pin; pinned.has(id)?pinned.delete(id):pinned.add(id); savePins(); renderClaims(); return; }
  const row=e.target.closest(".row"); if(row){ row.classList.toggle("open"); return; }
  const tb=e.target.closest("#tabs button");
  if(tb){ tab=tb.dataset.t; [...tb.parentNode.children].forEach(c=>c.classList.toggle("on",c===tb));
    ["claims","squad","league"].forEach(t=>document.getElementById("tab-"+t).hidden=(t!==tab)); window.scrollTo(0,0); return; }
  const ch=e.target.closest("#chips button");
  if(ch){ posFilter=ch.dataset.v||null; [...ch.parentNode.children].forEach(c=>c.classList.toggle("on",c===ch)); renderClaims(); return; }
  if(e.target.id==="refresh"){ poll(true); }
});
document.getElementById("chips").innerHTML=[["All",""],...POS.map(p=>[p,p])]
  .map(([l,v])=>`<button data-v="${v}" class="${v===""?"on":""}">${l}</button>`).join("");
const q=document.getElementById("q");
q.addEventListener("keydown",e=>{
  if(e.key!=="Enter") return;
  const t=q.value.trim().toLowerCase(); if(!t||!D) return;
  const hit=(D.claims||[]).filter(r=>r.s.includes(t)).sort((a,b)=>b.pw-a.pw)[0];
  if(hit){ pinned.add(hit.i); savePins(); q.value=""; q.blur(); posFilter=null;
    [...document.getElementById("chips").children].forEach((c,i)=>c.classList.toggle("on",i===0)); renderClaims(); }
  else { q.value=""; q.placeholder="No free agent by that name"; setTimeout(()=>q.placeholder="Search a free agent to pin",1800); }
});

async function poll(manual){
  if(manual) setStatus("live","refreshing");
  try{
    const r=await fetch(DATA_URL+(STATIC?"?t="+Date.now():""),{cache:"no-store"});
    if(!r.ok) throw new Error("HTTP "+r.status);
    D=await r.json(); lastFetch=Date.now(); saveCache(); render();
    if(STATIC) setStatus(D.error?"stale":"live", `${D.error?"stale":"synced"} ${ago(D.built)} · GW${D.gw} done`);
    else setStatus(D.error?"stale":"live", D.error?"stale":`live · GW${D.gw} done`);
  }catch(e){
    setStatus("err", D?`offline · showing ${ago(D.built)}`:(STATIC?"not reachable":"PC not reachable"));
    if(D) render();
  }
}
loadLocal();
if(D){ render(); setStatus("stale",`cached · ${ago(D.built)}`); }
if(STATIC&&REPO){ const a=document.getElementById("ghlink"); a.href=`https://github.com/${REPO}/actions/workflows/waivers.yml`; a.hidden=false; }
poll();
setInterval(poll, STATIC?300000:30000);
document.addEventListener("visibilitychange",()=>{ if(!document.hidden && Date.now()-lastFetch>10000) poll(); });
setInterval(()=>{ if(D) document.getElementById("upd").textContent=`board ${ago(D.built)} · data ${D.data_age_h}h old`; },15000);
</script>
</body>
</html>
"""


def render_page(data_url: str = "/api/mobile", static: bool = False,
                repo: str = "") -> str:
    return (PAGE.replace("__DATA_URL__", data_url)
                .replace("__STATIC__", "true" if static else "false")
                .replace("__REPO__", repo))


def manifest(start_url: str = "/m") -> str:
    return json.dumps({
        "name": "FPL Draft Waivers", "short_name": "Waivers",
        "start_url": start_url, "display": "standalone",
        "background_color": "#0e3c2c", "theme_color": "#0e3c2c",
        "icons": [{"src": "icon.png", "sizes": "180x180", "type": "image/png"}],
    })


# Kept for anything that imported the old constant.
MANIFEST = manifest("/m")


def write_site(payload: dict, out_dir: str, repo: str = "") -> list[str]:
    """Write the phone board as a static site: index.html + data.json + icon.

    This is what the GitHub Actions workflow publishes to GitHub Pages, so the
    phone can read the board from anywhere with no PC involved. Everything is
    referenced relatively because Pages serves a project site under a
    sub-path (username.github.io/repo/).
    """
    import os
    os.makedirs(out_dir, exist_ok=True)
    files = {
        "index.html": render_page("data.json", static=True, repo=repo).encode("utf-8"),
        "data.json": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "icon.png": icon_png(),
        "manifest.webmanifest": manifest("./").encode("utf-8"),
        # Tells Pages not to run Jekyll, which would otherwise ignore some files.
        ".nojekyll": b"",
    }
    written = []
    for name, body in files.items():
        path = os.path.join(out_dir, name)
        with open(path, "wb") as fh:
            fh.write(body)
        written.append(path)
    return written

QR_PAGE = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open on your phone</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:#0e3c2c;color:#d9f5e5}
  .box{text-align:center;padding:24px}
  #qr{background:#fff;padding:16px;border-radius:14px;display:inline-block}
  code{font-size:22px;display:block;margin:16px 0 6px;color:#fff}
  p{margin:6px 0;opacity:.85;max-width:420px}
</style></head><body><div class="box">
<div id="qr"></div>
<code>__PHONE_URL__</code>
<p>Point the iPhone camera at this, or type the address into Safari.
Same Wi-Fi as this PC. Then Share &rarr; Add to Home Screen.</p>
<p id="warn" style="color:#fbbf24"></p>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>
  try{ new QRCode(document.getElementById("qr"),{text:"__PHONE_URL__",width:220,height:220}); }
  catch(e){ document.getElementById("warn").textContent="QR library did not load (no internet?). Type the address instead."; }
</script></body></html>"""
