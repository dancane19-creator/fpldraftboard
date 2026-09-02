"""
Data layer for the FPL Draft board.

Pulls from two public, no-auth-required endpoints:

  1. https://draft.premierleague.com/api/bootstrap-static
     The Draft game's player list. Gives us `draft_rank` (FPL's own preseason
     draft ranking), set-piece order fields, injury status, and positions.

  2. https://fantasy.premierleague.com/api/bootstrap-static/
     The Classic game's player list. Gives us `now_cost`. Price is Classic-only
     and irrelevant to Draft scoring, but it is extremely useful as a *signal*:
     it is FPL's own paid valuation of how many points they expect a player to
     score. We join it in on the `code` field, which is stable across both games.

Neither endpoint needs a league ID or a login.

Optionally (--deep) we also hit:
  3. https://fantasy.premierleague.com/api/element-summary/{id}/
     which returns `history_past` = that player's totals for every prior season.
     This is the only way to get last-season output during preseason, because
     the bootstrap counting stats are all reset to 0 before Gameweek 1.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

DRAFT_BOOTSTRAP = "https://draft.premierleague.com/api/bootstrap-static"
DRAFT_GAME = "https://draft.premierleague.com/api/game"
CLASSIC_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
CLASSIC_SUMMARY = "https://fantasy.premierleague.com/api/element-summary/{}/"
FIXTURES = "https://fantasy.premierleague.com/api/fixtures/?future=1"

# The FPL servers reject requests with a default urllib user agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def _get_json(url: str, timeout: int = 30, retries: int = 3) -> Any:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - we want to retry on anything
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_err!r}")


def _cache_path(name: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def fetch_all(deep: bool = False, use_cache: bool = True,
              max_age_hours: float = 6.0) -> dict:
    """Fetch (or load from cache) everything the board needs.

    Returns a dict with keys: draft, classic, past (maybe empty), game.
    """
    snap_file = _cache_path("snapshot.json")

    if use_cache and os.path.exists(snap_file):
        age_h = (time.time() - os.path.getmtime(snap_file)) / 3600.0
        if age_h < max_age_hours:
            with open(snap_file, "r", encoding="utf-8") as fh:
                snap = json.load(fh)
            # Only reuse the cache if it already has the depth we asked for.
            if (not deep or snap.get("past")) and snap.get("fixtures"):
                snap["_cache_age_hours"] = round(age_h, 2)
                return snap

    draft = _get_json(DRAFT_BOOTSTRAP)
    classic = _get_json(CLASSIC_BOOTSTRAP)
    game = _get_json(DRAFT_GAME)
    # Upcoming fixtures carry FPL's own difficulty rating per side, which is
    # what the next-five strip on the dashboard is built from.
    try:
        fixtures = _get_json(FIXTURES)
    except Exception:
        fixtures = []

    past: dict[str, Any] = {}
    if deep:
        past = _fetch_history(classic)

    snap = {
        "fetched_at": time.time(),
        "draft": draft,
        "classic": classic,
        "game": game,
        "past": past,
        "fixtures": fixtures,
    }
    with open(snap_file, "w", encoding="utf-8") as fh:
        json.dump(snap, fh)
    snap["_cache_age_hours"] = 0.0
    return snap


def _fetch_history(classic: dict) -> dict:
    """Pull last-season totals for every player. ~700 requests, threaded."""
    ids = [e["id"] for e in classic.get("elements", [])]
    out: dict[str, Any] = {}

    def one(pid: int):
        try:
            data = _get_json(CLASSIC_SUMMARY.format(pid), timeout=20, retries=2)
            return pid, data.get("history_past", [])
        except Exception:
            return pid, None

    # 8 workers keeps us polite; the whole sweep lands in roughly 1-2 minutes.
    with ThreadPoolExecutor(max_workers=8) as pool:
        for pid, hist in pool.map(one, ids):
            if hist is not None:
                out[str(pid)] = hist
    return out


def load_snapshot(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_snapshot(snap: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snap, fh)
