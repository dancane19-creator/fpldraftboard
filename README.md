# FPL Draft Board

[![GitHub](https://img.shields.io/badge/GitHub-dancane19--creator%2Ffpldraftboard-181717?logo=github)](https://github.com/dancane19-creator/fpldraftboard)

A best-available draft assistant for FPL Draft 2026/27. Ranks every player by
**VORP** (value over replacement player), tracks picks live, and tells you who
to take on the clock.

---

## In season: the waiver board on your phone, no PC needed

The draft is done, so the part that matters now is waivers. `waivers.py`
scores every free agent against **your own weakest starter** and lists claims
in the order to submit them. Three ways to look at it:

| | Command | Where it runs |
|---|---|---|
| Desktop page | `py draft.py waivers` | your PC, `localhost:8787` |
| Phone page over Wi-Fi | `py draft.py mobile` | your PC, phone on the same Wi-Fi |
| Phone page, hosted | GitHub Actions runs `py draft.py publish` | GitHub, from anywhere |

### The hosted one (set up once, then forget it)

GitHub runs the Python every 30 minutes and hosts the result as a page. Open
it on the phone from anywhere and add it to the home screen.

1. Repo → **Settings → Pages** → Source: **GitHub Actions**
2. Repo → **Settings → Secrets and variables → Actions → Variables** tab →
   New repository variable, twice: `FPL_LEAGUE` = your league id,
   `FPL_ENTRY` = your entry id (`py draft.py whoami --league <id>` lists them)
3. Repo → **Actions → Waiver board → Run workflow**

About a minute later the page is at
`https://dancane19-creator.github.io/fpldraftboard/`. In Safari: Share →
**Add to Home Screen**.

How it behaves:

- Rebuilds at :07 and :37 every hour. GitHub's scheduler can run late when it
  is busy; the page shows how old the board is, and **Run now** at the bottom
  takes you to the button that forces a rebuild.
- The page keeps the last board it saw, so it opens instantly and works
  offline, stamped with its age. Pins (the star) are stored on the phone.
- If a run fails (the FPL API goes down for an hour some weeks) the previous
  board stays up; nothing is replaced by an error page.
- GitHub pauses scheduled workflows after 60 days with no commits, and emails
  you first. Any commit resets the clock.

### The Wi-Fi one

```powershell
py draft.py mobile
```

Same page, served from your PC to your phone on the same Wi-Fi, refreshing
every 30 seconds. The PC prints the address and opens a QR code to scan. The
first time, Windows asks whether Python may use the network: allow it on
**private** networks.

---

## The league ID question

**You don't need one.** This is the main thing to clear up before today.

Player data on the Draft game is served from a completely public endpoint that
requires no login, no token and no league:

```
https://draft.premierleague.com/api/bootstrap-static
```

That returns every player in the game with positions, teams, injury status,
set-piece order and FPL's own `draft_rank`. I confirmed it's live and already
loaded for 2026/27 (`/api/game` currently returns `next_event: 1`, meaning
Gameweek 1 hasn't started yet).

A league ID only unlocks things that are specific to *your* league:

| What you want | Needs league ID? | Needs login? |
|---|---|---|
| All players, positions, injuries, set-piece takers | No | No |
| Draft rankings | No | No |
| Who your rivals have drafted | Yes | Yes |
| Live standings, waivers, trades | Yes | Yes |

Since you're marking picks by hand as they happen, the board never needs it.

### If you do want it later

The reliable way is the browser. Log in at `draft.premierleague.com`, open your
league, and read the address bar. The numeric segment after `/league/` is your
league ID:

```
https://draft.premierleague.com/league/123456/standings
                                        ^^^^^^
```

If it isn't visible there, open DevTools (F12) → Network tab → filter on
`api` → reload the page. The requests the site fires at itself will contain
your league ID and your entry ID. Those league endpoints need your session
cookie, so any script hitting them has to send the cookie your browser already
has.

---

## The live dashboard

```bash
py draft.py --deep --teams 10 fetch
py draft.py serve --league 721 --entry 2438
```

That opens `http://localhost:8777` and follows your league's own draft record.
Picks appear on their own, your snake slot is detected from the data, and the
recommendation updates as the board thins. Nothing to type.

**Why a server rather than a file.** A page opened from `file://` has a null
origin, so the browser blocks it from fetching draft.premierleague.com unless
that API sends permissive CORS headers, which is not something to bet a draft
on. Serving from localhost and proxying `/api/*` through Python sidesteps it
entirely: the page only ever talks to its own origin.

What's on screen, top to bottom:

- **Status strip** - live indicator, the draft's current round and pick, and
  your slot once it has been detected.
- **Clock** - who is on the clock, your next pick number, and how many picks
  until then. Turns amber at two away and green when it's you.
- **Take now** - the pick, why, and three alternates.
- **Your squad** - what you hold and what you still need.
- **Best available by position** - four columns, tier breaks drawn in, with
  each player's chance of lasting until your next turn.
- **Position runs** - how many of each position went in the last ten picks. A
  column turns red at four or more, which is what a run looks like while it is
  happening rather than after.
- **Draft log** - every pick, grouped by round, yours highlighted.

### Manual mode

```bash
py draft.py --teams 10 --slot 3 export
```

Same dashboard written to a file, driven by typing names: Enter marks a player
drafted by someone else, Shift+Enter claims him for you. Use it when there is
no league to follow, or as a backup if the API goes down mid-draft.

---

## The Excel version

```bash
python3 draft.py --teams 10 export-xlsx
```

Needs `openpyxl` (`py -m pip install openpyxl`) and Excel 2019 or 365, because
the replacement-level formula uses MINIFS.

Writes `draft-board.xlsx` with five tabs. It opens on **Board**, one row per
player. Set the yellow **Status** dropdown to `GONE` or `MINE` as picks happen
and every VORP in the sheet recalculates. Drafted rows grey out and strike
through; your own picks turn green.

- **Board** the player list, with AutoFilter so you can re-sort by VORP
- **My Squad** counts, what you still need, best available at each position
- **Guide** how it works, in the file itself
- **Calc** replacement level per position, the engine room
- **Settings** league size, the one cell you edit

Two honest limitations versus the HTML board:

- **Sorting is manual.** Excel can't re-sort itself without array formulas that
  don't survive being written by a script, so use the filter arrow on the VORP
  column when you want the board reordered.
- **Tier is a snapshot** from generation time and does not update. VORP and
  best-available do update live.

For those reasons the HTML board is the better tool during a live draft. The
Excel one is better for prep, note-taking and sorting things your own way.

---

## Syncing from your real league

Both of these endpoints turned out to be **public, no login required**:

```
draft.premierleague.com/api/league/<league id>/details   -> the managers
draft.premierleague.com/api/draft/<league id>/choices    -> every pick made
```

So the league ID is the only thing you need, and it is in the address bar when
you open your league: `/league/`**`123456`**`/standings`.

If it isn't showing there, there's a script for it:

```bash
py find_league.py                  # borrows your browser's existing login
py find_league.py --entry 123456   # no login at all, if you know your entry id
py find_league.py --paste          # paste the API response
py find_league.py --console        # browser console snippet, most reliable
```

It tries three routes in order of how little work they ask of you. The entry-id
route is fully public and involves no credentials whatsoever; your entry id is
in the URL when you view your own team, at `/entry/`**`123456`**`/event/1`. The
paste route needs nothing installed and no credential ever reaches the script.

From the terminal:

```bash
py draft.py whoami --league 123456          # lists the managers, find your entry id
py draft.py sync --league 123456 --entry 42 # pulls every pick, rewrites state
py draft.py --teams 10 --slot 3 export      # rebuild the board from it
```

From the board itself, no terminal: click **Sync league**, open
`draft.premierleague.com/api/draft/123456/choices` in a browser tab, copy the
whole page, paste it in, pick your team name from the dropdown, hit Load picks.

Sync treats the league as the source of truth and replaces local state, so
anything you tracked by hand that disagrees with the league was wrong. It reads
`choices` for the draft order and `element_status` for current ownership, which
catches anything that moved on waivers or via trade afterwards.

---

## The draft log

Once any pick is recorded the board shows a log underneath the controls:
every player taken, newest first, grouped by round, with your own picks
highlighted. Pick numbers come from the league's own record when you sync, and
are derived from the order you marked them otherwise.

---

## Setup for the command-line version

Python 3.9+, no third-party packages needed.

```bash
cd fpl_draft
python3 draft.py --deep --teams 8 fetch
```

`--deep` pulls each player's prior-season totals, which takes roughly a minute
or two and makes the projections noticeably better. Set `--teams` to the number
of managers in your league; it changes where replacement level sits, which
changes everything downstream. Data is cached in `cache/` for 6 hours; add
`--refresh` to force a re-pull.

**One check before you rely on it:** `fetch` prints how many players came back
and how many have history. If it prints 0 players, the Draft game isn't serving
data yet and nothing else will work.

---

## Using it during the draft

Interactive mode is the one to use when you're on the clock:

```bash
python3 draft.py live --until-next 14
```

`--until-next` is how many picks happen between your turns. In an 8-team snake
that's about 14 on average, and it's what drives the run-risk warnings.

Inside live mode:

| Type | Meaning |
|---|---|
| `haaland` | someone else drafted him |
| `+saka` | **you** drafted him |
| `b` | best available right now |
| `board DEF` | full board, filtered to a position |
| `r` | your squad and what you still need |
| `s` | positional scarcity |
| `u` | undo the last entry |
| `q` | quit |

Names are fuzzy-matched. If one is ambiguous it shows you the candidates and
tells you which it used, so type more letters if it guessed wrong.

Every command also works as a one-shot from the shell if you prefer:

```bash
python3 draft.py gone haaland
python3 draft.py mine saka
python3 draft.py best
python3 draft.py board MID -n 30
python3 draft.py roster
python3 draft.py reset          # wipe state and start over
```

State lives in `draft_state.json`, so you can close the terminal and pick up
where you left off.

---

## How the ranking works

**Why VORP instead of projected points.** In Classic FPL you have a budget, so
value means points per million. In Draft there's no budget: every player costs
exactly one pick. So the only question is how many points a player gives you
over the guy you could get at that position later. Replacement level is the
projected output of the last player at each position who'd realistically be in
someone's starting XI.

The practical effect: a forward projected for 140 when the 16th-best forward
gets 120 is worth *less* than a defender projected for 125 when the 32nd-best
defender gets 88. Most people draft off a flat points list and systematically
overdraft forwards. Replacement level is recomputed from whoever is still on
the board, so the recommendations shift as positions dry up.

**Projections.** Preseason, every counting stat in the API is reset to zero, so
there's no form or xG to lean on yet. The model blends what does exist:

- Classic FPL price, joined in on the cross-game `code` field. Price is
  meaningless for Draft scoring but it's FPL's own paid valuation of expected
  output, and it encodes transfers and role changes that last season can't.
- `draft_rank`, FPL's own preseason draft ordering.
- Last season's points per 90, for anyone with 600+ minutes (`--deep` only).
- `ep_next`, FPL's expected points for the coming round.
- Set-piece order. First-choice penalties are worth about 22 points a season to
  a forward or midfielder; corners about 10 to a midfielder or defender.
- Injury status and `chance_of_playing`, as an availability multiplier.

Returning players get weighted 42% price / 30% last season / 20% draft rank /
8% ep. Players with no top-flight history (promoted clubs, new signings) fall
back to 58% price / 32% draft rank / 10% ep and get flagged `[no PL history]`
so you know the projection is softer.

Those blended scores are ranked within position, then mapped onto a season
points curve calibrated to what real Draft seasons look like. Only the
*differences* matter, since VORP is a subtraction.

**Tiers.** The `t1`, `t2` column groups players whose VORP is within about 8
points of each other. Inside a tier, take whoever you like. Between tiers is
where a reach is actually justified.

**Defensive contribution.** Unchanged for 2026/27: a defender banks 2 points for
10+ clearances, blocks, interceptions and tackles in a match, a midfielder or
forward needs 12 of those plus recoveries, capped at 2 points per match. It is
the most reliable points source a defender has, because it does not depend on
the team keeping a clean sheet. Defenders on bad teams do more defending. It is
weighted hardest at DEF, lightly at MID, and players in the top eighth of the
rate at their position carry a `DEFCON` flag. (BPS was also retuned this season
to overlap less with these points.)

---

## Reading the board: Lasts and Market

Two columns exist to tell you what VORP can't, which is whether you need to
take someone *now*.

**Lasts** is the chance a player is still on the board at your next turn. It
comes from your snake slot (so it knows you wait 18 picks at slot 1 and 0 at
the turn) crossed with FPL's published ordering. Red means take him or lose
him. Green means relax.

**Market** is FPL's own preseason rank, with a coloured number showing how far
that sits from where your board has him. Green `+60` means the market rates him
60 spots lower than you do, so you can probably wait a round and still get him.
Red means the opposite: the field likes him more than your model does, and
you'd be paying up.

The pair together is the actual edge. A defender at 100% to last with a green
`+60` is someone you should never spend an early pick on, however good his VORP
looks in isolation.

---

## How well does it work

All numbers below come from paired simulations: the same draft slot is replayed
with the same seed and the same rivals, changing only the strategy, averaged
over all 10 slots. That control matters. My first attempt at this test seated
one strategy at slot 2 and another at slot 7, and measured slot advantage
rather than strategy.

**VORP versus drafting by projected points.** This is the real finding:

```
naive points vs plain VORP:  -67.5 XI pts when rivals follow FPL's rankings
                             -35.0 XI pts when rivals value players themselves
                             worse in 98 of 100 drafts
```

**The scarcity tilt on top of VORP.** This one is marginal and I'd rather say so:

```
tilted vs plain VORP:  between -1 and +29 XI pts when rivals follow FPL's rankings
                       between -7 and  +1 XI pts when rivals value players themselves
```

That is a range, not a number, because it swings substantially with the random
seed of the synthetic test data. Which is the finding: the tilt is somewhere
between noise and a modest gain, and it depends on your league-mates drafting
off the published rankings rather than their own valuations. It is a bet on
market inefficiency, not a free lunch. Cranking it up makes things steadily
worse (at full strength it costs 10 to 15 points). It ships at 0.30; set
`LOOKAHEAD = 0.0` in `strategy.py` for plain VORP.

Worth being straight about the limits. Every strategy here is scored by the same
projection model, so these tests measure whether the *allocation* logic is
sound, not whether the underlying numbers are right. Preseason, with every
counting stat reset to zero, the projections are the weak link and no amount of
allocation cleverness fixes that. They get much better a few gameweeks in.

---

## Testing without the API

`make_mock.py` builds a synthetic snapshot with the same field names and shapes
as the real endpoints, so you can rehearse the whole flow:

```bash
python3 make_mock.py
python3 draft.py --snapshot mock_snapshot.json --teams 8 live
```

`sim_test.py` runs a full 120-pick draft and asserts the squad comes out legal.
`strategy_test.py` runs the head-to-head above.

---

## Files

| File | What it does |
|---|---|
| `draft.py` | CLI and live mode |
| `model.py` | projections, VORP, tiers |
| `fpl_data.py` | API calls and caching |
| `make_mock.py` | synthetic test data |
| `sim_test.py` | full-draft invariant checks |
| `strategy_test.py` | VORP vs naive comparison |
| `dashboard.py` | builds the dashboard, live and manual |
| `serve.py` | local server + API proxy for live mode |
| `season.py` | in-season projections and gain-over-your-starter scoring |
| `waivers.py` | the desktop waiver page |
| `mobile.py` | the phone waiver page, Wi-Fi and GitHub-hosted |
| `.github/workflows/waivers.yml` | the scheduled GitHub build |
| `export_xlsx.py` | builds the Excel workbook |
| `sync.py` | reads your league's live draft record |
| `find_league.py` | finds your league ID |
| `CHECKLIST.md` | the step-by-step guide |
| `checklist.html` | same guide, in the browser |
| `SLEEPERS.md` | promoted-team research |
