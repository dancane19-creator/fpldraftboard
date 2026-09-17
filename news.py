"""Headlines for the players on the board, from open RSS feeds. No key.

Two layers of "news" feed the board, and it matters which is which:

  1. **FPL's own availability note** (the `news` field on every player, with
     `chance_of_playing_next_round`). This is the Premier League's official
     line: "Knee injury - Expected back 25 Sep", "Suspended until 20 Sep",
     "75% chance of playing". It is structured, it is what the game itself
     uses, and season.py turns it into numbers: chance of playing next week,
     return gameweek, how many matches he misses. That is what moves the
     projections and the drop decision. It comes with the data we already
     pull, so it needs nothing from this module.

  2. **Headlines**, which is what this module adds. The Premier League has no
     open news API, so this reads public RSS feeds instead: BBC Sport's
     per-club feed for each Premier League club, plus the general BBC, Sky
     Sports and Guardian football feeds. Items are matched to players by
     surname (and to clubs), and the latest few are attached to each player
     and each club for the detail sheet. Headlines are context for a human,
     never an input to the model: a headline saying a player "could start"
     is not a fact the way a 0% chance-of-playing flag is.

Everything here is best effort. A feed being down, slow or renamed produces
an empty list, never a failed build.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

from fpl_data import CACHE_DIR, HEADERS

# BBC per-club feeds live at this pattern. Club names in FPL's feed are short
# ("Man City", "Nott'm Forest", "Spurs"), so map the odd ones by hand and
# derive the rest.
BBC_TEAM = "https://feeds.bbci.co.uk/sport/football/teams/{}/rss.xml"
BBC_SLUG = {
    "Man City": "manchester-city", "Man Utd": "manchester-united",
    "Spurs": "tottenham-hotspur", "Nott'm Forest": "nottingham-forest",
    "Wolves": "wolverhampton-wanderers", "Brighton": "brighton-and-hove-albion",
    "Newcastle": "newcastle-united", "West Ham": "west-ham-united",
    "Leeds": "leeds-united", "Hull": "hull-city", "Coventry": "coventry-city",
    "Ipswich": "ipswich-town", "Leicester": "leicester-city",
    "Sheffield Utd": "sheffield-united", "Luton": "luton-town",
    "Norwich": "norwich-city", "Blackburn": "blackburn-rovers",
    "West Brom": "west-bromwich-albion", "Preston": "preston-north-end",
    "QPR": "queens-park-rangers", "Charlton": "charlton-athletic",
    "Derby": "derby-county", "Stoke": "stoke-city", "Swansea": "swansea-city",
    "Cardiff": "cardiff-city", "Oxford": "oxford-united",
    "Sheffield Wed": "sheffield-wednesday", "Plymouth": "plymouth-argyle",
    "Birmingham": "birmingham-city", "Bristol City": "bristol-city",
}
GENERAL_FEEDS = [
    ("BBC", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("Sky Sports", "https://www.skysports.com/rss/12040"),
    ("Guardian", "https://www.theguardian.com/football/rss"),
]

CACHE_FILE = os.path.join(CACHE_DIR, "news.json")
CACHE_TTL = 30 * 60          # seconds; the workflow runs every 30 minutes anyway
MAX_PER_PLAYER = 3
MAX_PER_TEAM = 4
MAX_AGE_DAYS = 10


def _slug(team_name: str) -> str:
    if team_name in BBC_SLUG:
        return BBC_SLUG[team_name]
    s = unicodedata.normalize("NFKD", team_name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _fetch(url: str, timeout: int = 12) -> list[dict]:
    """One feed -> [{t, u, d, src}] or [] on any problem."""
    try:
        req = urllib.request.Request(url, headers=dict(HEADERS, Accept="*/*"))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except Exception:
        return []
    items = []
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        desc = html.unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or ""))
        pub = it.findtext("pubDate") or ""
        try:
            ts = parsedate_to_datetime(pub).timestamp()
        except Exception:
            ts = 0.0
        if title and link:
            items.append({"t": title, "u": link, "d": ts, "x": desc.strip()[:300]})
    return items


def fetch_feeds(team_names: list[str]) -> dict:
    """All feeds, cached on disk so repeated local runs don't hammer anyone.

    Returns {"at": epoch, "teams": {team_name: [items]}, "general": [items]}.
    """
    try:
        if os.path.exists(CACHE_FILE) and time.time() - os.path.getmtime(CACHE_FILE) < CACHE_TTL:
            with open(CACHE_FILE, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            if set(cached.get("teams", {})) >= set(team_names):
                return cached
    except Exception:
        pass

    jobs = [(name, BBC_TEAM.format(_slug(name)), "BBC") for name in team_names]
    jobs += [(None, url, src) for src, url in GENERAL_FEEDS]
    out = {"at": time.time(), "teams": {}, "general": []}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for (name, url, src), items in zip(jobs, pool.map(lambda j: _fetch(j[1]), jobs)):
            for it in items:
                it["src"] = src
            if name is None:
                out["general"].extend(items)
            else:
                out["teams"][name] = items
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
    except Exception:
        pass
    return out


def _mentions(text: str, needle: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", text) is not None


def attach(players, snap: dict) -> dict:
    """Give every player a `headlines` list and return per-club headlines.

    Club feeds are already scoped to the club, so a surname is enough there.
    On the general feeds a surname alone is too loose ("King", "White"), so
    those need the club or the first name in the same item.
    """
    teams = (snap.get("draft") or {}).get("teams") or []
    names = [t.get("name", "") for t in teams if t.get("name")]
    short_by_name = {t.get("name"): t.get("short_name") for t in teams}
    feeds = fetch_feeds(names)
    cutoff = time.time() - MAX_AGE_DAYS * 86400

    def fresh(items):
        return sorted([i for i in items if i.get("d", 0) >= cutoff],
                      key=lambda i: -i.get("d", 0))

    team_items = {name: fresh(items) for name, items in feeds.get("teams", {}).items()}
    general = fresh(feeds.get("general", []))
    for items in team_items.values():
        for it in items:
            it["_f"] = _fold(it["t"] + " " + it.get("x", ""))
    for it in general:
        it["_f"] = _fold(it["t"] + " " + it.get("x", ""))

    by_short = {}
    for p in players:
        surname = _fold(p.full_name.split()[-1] if p.full_name else p.name)
        first = _fold(p.full_name.split()[0]) if p.full_name and " " in p.full_name else ""
        web = _fold(p.name)
        club = _fold(p.team)
        hits = []
        for it in team_items.get(p.team, []):
            if _mentions(it["_f"], surname) or (web != surname and _mentions(it["_f"], web)):
                hits.append(it)
        for it in general:
            if (_mentions(it["_f"], surname) or (web != surname and _mentions(it["_f"], web))) \
                    and (_mentions(it["_f"], club) or (first and _mentions(it["_f"], first))):
                hits.append(it)
        seen, out = set(), []
        for it in sorted(hits, key=lambda i: -i.get("d", 0)):
            if it["u"] in seen:
                continue
            seen.add(it["u"])
            out.append({"t": it["t"], "u": it["u"], "d": it["d"], "src": it["src"]})
            if len(out) >= MAX_PER_PLAYER:
                break
        p.headlines = out
        by_short.setdefault(short_by_name.get(p.team, p.team_short), None)

    club_news = {}
    for name, items in team_items.items():
        club_news[short_by_name.get(name, name)] = [
            {"t": i["t"], "u": i["u"], "d": i["d"], "src": i["src"]}
            for i in items[:MAX_PER_TEAM]]
    return {"at": feeds.get("at", 0), "clubs": club_news,
            "sources": [s for s, _ in GENERAL_FEEDS] + ["BBC club feeds"]}
