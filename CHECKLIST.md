# FPL Draft Board: the step-by-step

Windows / PowerShell. Substitute `python3` for `py` if you ever run this on a Mac.

---

## Part 1: One-time setup (do once, ever)

**1.1 Check Python is installed.**

```powershell
py --version
```

Expect something like `Python 3.12.x`. If you get "not recognized":

```powershell
winget install Python.Python.3.12
```

Close PowerShell, reopen it, try again. Use `py`, not `python3` — that command
does not exist on Windows. If `py` fails but `python` works, use `python`.

**1.2 Unzip the board somewhere permanent.**

Not Downloads. Something like `C:\Users\dcane\fpl-draft`.

**1.3 Only if you want the Excel version:**

```powershell
py -m pip install openpyxl
```

The HTML board needs nothing installed.

---

## Part 2: Before each draft (about 3 minutes)

**2.1 Open PowerShell in the folder.**

```powershell
cd C:\Users\dcane\fpl-draft
```

**2.1b Find your league ID, once per league.**

```powershell
py find_league.py
```

Falls back through three routes automatically. If none work, the ID is in the
address bar when you open your league: `/league/123456/standings`. Then:

```powershell
py draft.py whoami --league 123456           # find your entry number
py draft.py sync --league 123456 --entry 42  # pull every pick automatically
```

Sync is optional. Typing names as picks happen works fine without it.

**2.2 Pull fresh player data.**

```powershell
py draft.py --deep --teams 10 fetch
```

Set `--teams` to your actual league size. It decides where replacement level
sits, which drives every number downstream.

`--deep` adds last season's per-player history and takes a minute or two. Worth
it: without it the projections lean on price alone.

- [ ] It printed a player count in the hundreds. **If it printed 0, stop** —
      the Draft game is not serving data and nothing else will work.
- [ ] It printed a count of players with last-season history.

**2.3 Clear any old draft state.**

```powershell
py draft.py reset
```

Do this after every mock draft. Skip it and the board thinks 150 players are
already gone.

**2.4 Build the board.**

```powershell
py draft.py --teams 10 --slot 4 export
```

`--slot` is your pick number in round one. If you don't know it yet, put
anything; there's a dropdown in the page.

Optionally, for prep and note-taking:

```powershell
py draft.py --teams 10 export-xlsx
```

**2.5 Open `draft-board.html`.** Double-click it in File Explorer.

- [ ] **No yellow "Sample data" banner.** If you see one, you exported from the
      offline test set. Re-run step 2.2, then 2.4.
- [ ] Player names are real footballers.
- [ ] The header shows the right league size and your slot.

---

## Part 3: During the draft

**Your whole loop is: someone picks, you type their name, hit Enter.**

| Action | What to do |
|---|---|
| Someone else drafted a player | Type a few letters of his name, press **Enter** |
| **You** drafted a player | Type his name, press **Shift+Enter** |
| Made a mistake | Click **Undo** |
| See only defenders | Click **DEF** |
| Start over | Click **Reset** |

The cursor stays in the search box, so you can keep typing as picks fly.

**When it's your turn, read the TAKE NOW panel.** It gives you the player, the
reason in one sentence, and three alternates. If you're in a hurry that is the
only thing you need.

**When you have a moment, check two columns before you commit:**

- **Lasts** — chance he survives to your next turn. Red (under 30%) means take
  him now or lose him. Green (over 75%) means you can wait.
- **Market** — FPL's own rank, with a coloured offset. Green `+60` means the
  field rates him 60 spots lower than your board does, so you can probably wait
  a round and still get him.

**The one override worth knowing.** If the top recommendation is green on both
columns and someone just below is red on both, take the red one. You'll still
get the green player later. That's the single most valuable judgement call the
tool sets up for you, and it's the reason those columns exist.

**Trust tiers over small VORP gaps.** A 4-point VORP difference is inside the
noise of preseason projections. A tier break is a real cliff.

Your picks live in the address bar, so a refresh won't lose the draft. Bookmark
the URL mid-draft if you want a checkpoint.

---

## Part 4: What good looks like

Roughly what the maths produces, so you can sanity-check it live:

| Rounds | Usually |
|---|---|
| 1-4 | Midfielders and forwards. This is where the VORP cliffs are. |
| 5-9 | More attackers, your first genuine defenders |
| 10-13 | Defenders, especially high-DEFCON ones, first keeper |
| 14-15 | Second keeper, upside picks, promoted-team fliers |

If the board tells you to take a keeper in round 3, something is wrong with the
data — check for the sample-data banner.

**Never draft a promoted-team player before round 11.** Their whole value is
that they're free. The one exception is Leif Davis (Ipswich, LB), worth a round
or two earlier. See `SLEEPERS.md`.

---

## Part 5: After the draft

- [ ] `py draft.py reset` if you plan to run another draft
- [ ] Keep `SLEEPERS.md` handy for early-season waivers
- [ ] Charlie Hughes (Hull, CB) is out for Gameweek 1 and will go undrafted.
      He's the best defensive-contribution profile among the promoted clubs.
      Claim him on waivers the moment he's fit.

---

## Troubleshooting

**`python3 : The term 'python3' is not recognized`**
Use `py` on Windows. `python3` is Mac/Linux only.

**`unrecognized arguments: --deep --teams 10`**
You have an old copy. Flags now work before or after the subcommand. Re-unzip
the latest bundle.

**`fetch` printed 0 players**
The Draft game isn't serving data. Nothing downstream will work until it does.

**The board shows a yellow "Sample data" banner**
You exported from the offline test set. Run `fetch`, then `export` again.

**Excel: `#NAME?` in the VORP column**
Your Excel is older than 2019. The formula uses MINIFS. Use the HTML board.

**Everything says 0 players left**
You forgot `py draft.py reset` after a mock draft.

---

## Command reference

```powershell
py draft.py --deep --teams 10 fetch      # pull data (once per draft day)
py draft.py --teams 10 --slot 4 export   # build the HTML board
py draft.py --teams 10 export-xlsx       # build the Excel board
py draft.py reset                        # wipe draft state
py draft.py --slot 4 best                # recommendation, in the terminal
py draft.py live                         # interactive terminal mode
py draft.py board DEF -n 30              # top 30 defenders
py draft.py whoami --league 123456       # managers in your league
py draft.py sync --league 123456 --entry 42   # pull live picks
py find_league.py --console              # find your league ID (most reliable)
```

You never need a league ID to draft. It only unlocks the optional live sync.
