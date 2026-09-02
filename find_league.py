#!/usr/bin/env python3
"""Find your FPL Draft league ID.

    py find_league.py                    try your browser's login automatically
    py find_league.py --entry 123456     no login needed, if you know your entry id
    py find_league.py --paste            paste JSON, works when nothing else does
    py find_league.py --cookie "..."     supply a session cookie by hand
    py find_league.py --console          browser-console snippet, works when
                                         the API does not accept your cookies

Why this needs any effort at all
--------------------------------

Most of the Draft API is public. These two are:

    /api/entry/<entry id>/public      -> your team, and `league_set`, the list
                                         of league IDs you are in
    /api/league/<league id>/details   -> that league's name and its managers

But nothing public maps *you* to an entry id, because the API has no idea who
is asking. Only one endpoint does:

    /api/bootstrap-dynamic            -> your leagues, but only with your
                                         session cookie attached

So there are three ways in, and this script tries them in order of how little
work they ask of you.

  1. AUTO      read the premierleague.com cookies your browser already has.
               Zero effort when it works. Needs `browser_cookie3` installed,
               and recent Chrome versions sometimes encrypt cookies in a way
               that blocks it.
  2. ENTRY ID  if you know your entry id, the fully public route works with no
               credentials at all. Your entry id is in the address bar when you
               view your own team: /entry/<this number>/event/1
  3. PASTE     open the API URL in the browser where you are logged in, copy
               the page, paste it here. Always works, needs nothing installed,
               and no credential ever touches this script.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

BOOTSTRAP_DYNAMIC = "https://draft.premierleague.com/api/bootstrap-dynamic"
ENTRY_PUBLIC = "https://draft.premierleague.com/api/entry/{}/public"
LEAGUE_DETAILS = "https://draft.premierleague.com/api/league/{}/details"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def get_json(url: str, cookie: str | None = None, timeout: int = 25):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------- reporting --

def describe_league(league_id: int, cookie: str | None = None) -> str:
    """League name and size, so you can tell which of several is the right one."""
    try:
        d = get_json(LEAGUE_DETAILS.format(league_id), cookie)
        lg = d.get("league") or {}
        n = len(d.get("league_entries", []))
        bits = [lg.get("name", "?")]
        if n:
            bits.append(f"{n} managers")
        if lg.get("draft_status"):
            bits.append(f"draft {lg['draft_status']}")
        return "  -  ".join(bits)
    except Exception:
        return "(could not read league details)"


def report(leagues: list[dict], cookie: str | None = None) -> None:
    if not leagues:
        print("\n  No leagues found on that account.")
        return
    print(f"\n  Found {len(leagues)} league(s):\n")
    for lg in leagues:
        lid = lg.get("id")
        name = lg.get("name") or describe_league(lid, cookie)
        print(f"    LEAGUE ID  {lid}")
        print(f"               {name}")
        print()
    print("  Use it like this:\n")
    first = leagues[0].get("id")
    print(f"    py draft.py whoami --league {first}")
    print(f"    py draft.py sync   --league {first} --entry <your entry id>")


# ------------------------------------------------------------------ routes --

def route_cookie(cookie: str) -> list[dict] | None:
    try:
        data = get_json(BOOTSTRAP_DYNAMIC, cookie)
    except Exception as exc:
        print(f"  Request failed: {exc}")
        return None
    return parse_dynamic(data)


def parse_dynamic(data: dict) -> list[dict] | None:
    """Pull leagues out of a bootstrap-dynamic payload."""
    leagues = data.get("leagues") or []
    if leagues:
        return [{"id": lg.get("id"), "name": lg.get("name")} for lg in leagues]

    # Some payloads carry the leagues only via the entries they belong to.
    ids = []
    for e in data.get("entries", []):
        for lid in e.get("league_set", []) or []:
            if lid not in ids:
                ids.append(lid)
    if ids:
        return [{"id": i, "name": None} for i in ids]

    if not data.get("player"):
        print("\n  That response has no logged-in user attached, so the site")
        print("  did not recognise the session. The cookie is missing, stale,")
        print("  or from the wrong browser profile.")
    return []


def route_entry(entry_id: int) -> list[dict] | None:
    """Fully public: entry id -> league_set. No credentials involved."""
    try:
        data = get_json(ENTRY_PUBLIC.format(entry_id))
    except Exception as exc:
        print(f"  Could not read entry {entry_id}: {exc}")
        return None
    entry = data.get("entry") or {}
    if not entry:
        print(f"  No entry {entry_id} found.")
        return None
    who = f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip()
    print(f"\n  Entry {entry_id}: {entry.get('name','?')}"
          f"{f'  ({who})' if who else ''}")
    return [{"id": i, "name": None} for i in entry.get("league_set", [])]


def route_auto() -> list[dict] | None:
    """Borrow the login your browser already has."""
    try:
        import browser_cookie3
    except ImportError:
        print("  Automatic browser login needs one package:")
        print("      py -m pip install browser_cookie3")
        print("  Or skip it and use --entry or --paste, which need nothing.")
        return None

    jar_names = ["chrome", "edge", "firefox", "brave", "opera", "chromium"]
    for name in jar_names:
        loader = getattr(browser_cookie3, name, None)
        if loader is None:
            continue
        try:
            jar = loader(domain_name="premierleague.com")
        except Exception:
            continue
        cookie = "; ".join(f"{c.name}={c.value}" for c in jar)
        if not cookie:
            continue
        print(f"  Trying cookies from {name}...")
        leagues = route_cookie(cookie)
        if leagues:
            return leagues
    print("\n  No usable premierleague.com login found in any browser.")
    print("  Recent Chrome encrypts cookies in a way this cannot read, which")
    print("  is normal and not a sign anything is broken. Use --paste instead.")
    return None


CONSOLE_SNIPPET = (
    "(()=>{const s=new Set(),p=[/\\/api\\/(?:league|draft)\\/(\\d+)/g,"
    "/\\/league\\/(\\d+)/g],u=[...performance.getEntriesByType('resource')"
    ".map(e=>e.name),location.href];for(const x of u)for(const r of p)"
    "{r.lastIndex=0;let m;while(m=r.exec(x))s.add(m[1])}const a=[...s];"
    "console.log(a.length?'LEAGUE ID: '+a.join(', '):"
    "'None found - open your league page first, then run this again');"
    "return a})()"
)


def route_console() -> None:
    """Print a browser-console snippet that reads the ID off the live page.

    This is the route that survives everything else breaking. It does not care
    whether the API accepts your cookies, because it never calls the API: the
    site itself has already fetched your league, so the ID is sitting in the
    list of requests the page made. The Performance API can read that list back
    without any permissions.
    """
    print("\n  Works even when the API says you are logged out, because it")
    print("  reads what the page already loaded rather than asking the server.")
    print()
    print("  1. Open your league on draft.premierleague.com and let it load")
    print("  2. Press F12, click the Console tab")
    print("  3. Paste this, press Enter:")
    print()
    print("  " + "-" * 66)
    print(CONSOLE_SNIPPET)
    print("  " + "-" * 66)
    print()
    print("  It prints LEAGUE ID: <number>.")
    print()
    print("  If Firefox blocks pasting, it will ask you to type 'allow pasting'")
    print("  first. If nothing is found, click into the league standings so the")
    print("  page actually fetches it, then run the snippet again.")


def route_paste() -> list[dict] | None:
    print()
    print("  1. Make sure you are logged in at draft.premierleague.com")
    print("  2. Open this URL in that same browser:")
    print("         https://draft.premierleague.com/api/bootstrap-dynamic")
    print("  3. Select all (Ctrl+A), copy (Ctrl+C)")
    print("  4. Paste it below, then press Enter twice")
    print()
    print("  Nothing you paste is sent anywhere. It is parsed locally.")
    print("  ---")
    lines = []
    try:
        while True:
            line = input()
            if not line and lines:
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        pass
    raw = "".join(lines).strip()
    if not raw:
        print("  Nothing pasted.")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("  That was not valid JSON. Make sure you copied the whole page.")
        print("  If your browser shows a pretty JSON viewer, look for a 'Raw'")
        print("  tab and copy from there instead.")
        return None
    return parse_dynamic(data)


# -------------------------------------------------------------------- main --

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Find your FPL Draft league ID",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="If nothing here works, the league ID is in the address bar "
               "when you open your league:\n"
               "  https://draft.premierleague.com/league/123456/standings\n"
               "                                          ^^^^^^")
    ap.add_argument("--entry", type=int,
                    help="your entry id, for the fully public route")
    ap.add_argument("--cookie", help="a premierleague.com cookie string")
    ap.add_argument("--paste", action="store_true",
                    help="paste the API response instead")
    ap.add_argument("--console", action="store_true",
                    help="print a browser-console snippet that reads the ID "
                         "off the page (works when the API rejects cookies)")
    args = ap.parse_args()

    print("\nFPL Draft league ID finder")
    print("=" * 46)

    if args.console:
        route_console()
        return
    if args.entry:
        leagues = route_entry(args.entry)
    elif args.cookie:
        leagues = route_cookie(args.cookie)
    elif args.paste:
        leagues = route_paste()
    else:
        print("\n  Trying your browser's saved login...\n")
        leagues = route_auto()
        if leagues is None:
            print("\n  Falling back to paste mode.")
            leagues = route_paste()

    if leagues:
        report(leagues, args.cookie)
    else:
        print("\n  Nothing found. Two things that always work:")
        print("    - Open your league in a browser. The number in the URL")
        print("      after /league/ IS the league ID.")
        print("    - py find_league.py --console")
        print("      A snippet you paste into the browser console. It reads")
        print("      the ID off the page, so it works even when the API")
        print("      does not recognise your login.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
