"""Generate an Excel draft board with live-recomputing VORP.

The design problem: VORP depends on replacement level, and replacement level
depends on who is still available, so marking one player drafted has to ripple
through every other row. Excel can do that, but the modern array functions that
would make it easy (FILTER, SORT, XLOOKUP) can't be written safely from a
script, so everything here is built from SUMPRODUCT, INDEX/MATCH and MINIFS.

How the chain works:

  PosSeq     static, unique rank within position by projection (1 = best)
  AvailRank  SUMPRODUCT counting still-available players at the same position
             with a better PosSeq. Recalculates the instant a Status changes.
  Calc!D     replacement level per position, the projection of the available
             player whose AvailRank equals the Nth-starter cutoff
  VORP       projection minus that position's replacement level

Sorting is static because SORT can't be used. Use the AutoFilter arrows on the
header row to re-sort by VORP whenever you want the board reordered.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from model import SQUAD_LIMITS, TYPICAL_STARTERS, Player

POS = ["GKP", "DEF", "MID", "FWD"]

FONT = "Arial"
INK = "FF1A1A19"
MUTED = "FF898781"
ACCENT = "FF2A78D6"
GOOD = "FF0CA30C"
INPUT_BLUE = "FF0000FF"      # convention: hardcoded inputs are blue
YELLOW = "FFFFFF00"          # convention: cells the user should edit
HEAD_FILL = PatternFill("solid", fgColor="FFF0EFEC")
MINE_FILL = PatternFill("solid", fgColor="FFE4F5E4")
GONE_FILL = PatternFill("solid", fgColor="FFEDECE8")
THIN = Side(style="thin", color="FFE1E0D9")


def _style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, size=10, color=INK)
        cell.fill = HEAD_FILL
        cell.border = Border(bottom=Side(style="medium", color="FFC3C2B7"))
        cell.alignment = Alignment(horizontal="left", vertical="center")


def export_xlsx(players: list[Player], n_teams: int, path: str) -> str:
    # Static ordering: by projection descending, so PosSeq is well defined.
    ranked = sorted(players, key=lambda p: p.proj, reverse=True)[:340]

    pos_seq: dict[int, int] = {}
    seen = {pos: 0 for pos in POS}
    for p in ranked:
        seen[p.pos] = seen.get(p.pos, 0) + 1
        pos_seq[p.draft_id] = seen[p.pos]

    wb = Workbook()

    # ------------------------------------------------------------- Settings --
    st = wb.active
    st.title = "Settings"
    st["A1"] = "FPL Draft Board settings"
    st["A1"].font = Font(name=FONT, bold=True, size=13, color=INK)
    st["A3"] = "Managers in your league"
    st["B3"] = n_teams
    st["B3"].font = Font(name=FONT, bold=True, color=INPUT_BLUE)
    st["B3"].fill = PatternFill("solid", fgColor=YELLOW)
    st["C3"] = "<- edit this. It sets replacement level, which drives every VORP."
    st["A5"] = "Blue cells on a yellow fill are the only ones you should type into."
    st["A6"] = "Everything else is a formula and will update on its own."
    for r in (3, 5, 6):
        st[f"A{r}"].font = Font(name=FONT, size=10, color=INK)
    for r in (5, 6):
        st[f"A{r}"].font = Font(name=FONT, size=10, italic=True, color=MUTED)
    st["C3"].font = Font(name=FONT, size=10, italic=True, color=MUTED)
    st.column_dimensions["A"].width = 26
    st.column_dimensions["B"].width = 10
    st.column_dimensions["C"].width = 62

    # ---------------------------------------------------------------- Board --
    bd = wb.create_sheet("Board")
    # Full name goes LAST on purpose: every formula below addresses columns
    # A-K by letter, so appending keeps those references intact.
    headers = ["#", "Player", "Pos", "Team", "Proj", "Status", "VORP",
               "Tier", "Notes", "AvailRank", "PosSeq", "Full name"]
    bd.append(headers)
    _style_header(bd, 1, len(headers))

    n = len(ranked)
    last = n + 1                       # last data row
    C = f"$C$2:$C${last}"              # Pos
    E = f"$E$2:$E${last}"              # Proj
    F = f"$F$2:$F${last}"              # Status
    K = f"$K$2:$K${last}"              # PosSeq

    for i, p in enumerate(ranked, start=2):
        bd.cell(i, 1, i - 1)
        bd.cell(i, 2, p.name)
        bd.cell(i, 3, p.pos)
        bd.cell(i, 4, p.team_short)
        bd.cell(i, 5, round(p.proj))
        bd.cell(i, 6, None)            # Status: the dropdown
        # VORP: blank once drafted, otherwise projection minus replacement.
        bd.cell(i, 7, f'=IF($F{i}<>"","",$E{i}-INDEX(Calc!$D$2:$D$5,'
                      f'MATCH($C{i},Calc!$A$2:$A$5,0)))')
        bd.cell(i, 8, p.tier)
        bd.cell(i, 9, ", ".join(p.flags[:4]))
        # AvailRank: how many available players at this position are better.
        bd.cell(i, 10, f'=IF($F{i}<>"","",SUMPRODUCT(({C}=$C{i})*'
                       f'({F}="")*({K}<=$K{i})))')
        bd.cell(i, 11, pos_seq[p.draft_id])
        bd.cell(i, 12, p.full_name or p.name)

    for row in bd.iter_rows(min_row=2, max_row=last, max_col=len(headers)):
        for cell in row:
            cell.font = Font(name=FONT, size=10, color=INK)
            cell.border = Border(bottom=THIN)
        row[1].font = Font(name=FONT, size=10, bold=True, color=INK)
        row[0].font = Font(name=FONT, size=10, color=MUTED)
        row[4].number_format = "0"
        row[6].number_format = "+0.0;-0.0;0.0"
        row[6].font = Font(name=FONT, size=10, bold=True, color=INK)
        row[5].fill = PatternFill("solid", fgColor=YELLOW)
        row[5].font = Font(name=FONT, size=10, bold=True, color=INPUT_BLUE)

    dv = DataValidation(type="list", formula1='"GONE,MINE"', allow_blank=True,
                        showDropDown=False)
    dv.prompt = "GONE = drafted by someone else. MINE = drafted by you."
    dv.promptTitle = "Draft status"
    bd.add_data_validation(dv)
    dv.add(f"F2:F{last}")

    rng = f"A2:L{last}"
    bd.conditional_formatting.add(rng, FormulaRule(
        formula=[f'$F2="MINE"'], fill=MINE_FILL,
        font=Font(name=FONT, size=10, bold=True, color=GOOD)))
    bd.conditional_formatting.add(rng, FormulaRule(
        formula=[f'$F2="GONE"'], fill=GONE_FILL,
        font=Font(name=FONT, size=10, strike=True, color=MUTED)))

    bd.auto_filter.ref = f"A1:L{last}"
    bd.freeze_panes = "A2"
    for col, w in zip("ABCDEFGHIJKL",
                      [5, 22, 7, 8, 8, 10, 9, 7, 30, 11, 9, 26]):
        bd.column_dimensions[col].width = w
    # Working columns, kept visible-adjacent but out of the way.
    bd.column_dimensions["J"].hidden = True
    bd.column_dimensions["K"].hidden = True

    # ----------------------------------------------------------------- Calc --
    ca = wb.create_sheet("Calc")
    ca.append(["Pos", "Starters per team", "Replacement rank",
               "Replacement points", "Best available"])
    _style_header(ca, 1, 5)
    for i, pos in enumerate(POS, start=2):
        ca.cell(i, 1, pos)
        ca.cell(i, 2, TYPICAL_STARTERS[pos])
        ca.cell(i, 2).font = Font(name=FONT, size=10, color=INPUT_BLUE)
        # Replacement is the best player who does NOT start anywhere in the
        # league, so it is the first rank past the league-wide starter count:
        # 10 managers x 4 midfielders = 40 starters, so rank 41.
        ca.cell(i, 3, f"=ROUND($B{i}*Settings!$B$3,0)+1")
        # The Nth best available projection at this position: take everyone
        # with AvailRank at or above the cutoff, then the smallest of them.
        ca.cell(i, 4, f'=IFERROR(_xlfn.MINIFS(Board!{E},Board!{C},$A{i},'
                      f'Board!{F},"",Board!$J$2:$J${last},"<="&$C{i}),0)')
        ca.cell(i, 5, f'=IFERROR(INDEX(Board!$B$2:$B${last},'
                      f'SUMPRODUCT((Board!{C}=$A{i})*'
                      f'(Board!$J$2:$J${last}=1)*'
                      f'(ROW(Board!$B$2:$B${last})-1))),"-")')
    ca["A7"] = ("Starters per team is how many of each position a manager "
                "actually fields each week.")
    ca["A8"] = ("Draft formations allow 3-5 DEF, 2-5 MID and 1-3 FWD around "
                "one keeper, so these are the midpoints.")
    ca["A9"] = "Assumption set by Claude, not sourced from FPL. Edit if your league differs."
    for r in (7, 8, 9):
        ca[f"A{r}"].font = Font(name=FONT, size=9, italic=True, color=MUTED)
    for col, w in zip("ABCDE", [8, 18, 18, 19, 18]):
        ca.column_dimensions[col].width = w
    for row in ca.iter_rows(min_row=2, max_row=5, max_col=5):
        for cell in row:
            if cell.column != 2:
                cell.font = Font(name=FONT, size=10, color=INK)
        row[3].number_format = "0"

    # ---------------------------------------------------------------- Squad --
    sq = wb.create_sheet("My Squad")
    sq["A1"] = "My squad"
    sq["A1"].font = Font(name=FONT, bold=True, size=13, color=INK)
    sq.append([])
    sq.append(["Pos", "Drafted", "Limit", "Still need", "Best available now"])
    _style_header(sq, 3, 5)
    for i, pos in enumerate(POS, start=4):
        sq.cell(i, 1, pos)
        sq.cell(i, 2, f'=COUNTIFS(Board!{C},$A{i},Board!{F},"MINE")')
        sq.cell(i, 3, SQUAD_LIMITS[pos])
        sq.cell(i, 4, f"=$C{i}-$B{i}")
        sq.cell(i, 5, f"=INDEX(Calc!$E$2:$E$5,MATCH($A{i},Calc!$A$2:$A$5,0))")
    sq.cell(8, 1, "Total")
    sq.cell(8, 2, "=SUM($B$4:$B$7)")
    sq.cell(8, 3, "=SUM($C$4:$C$7)")
    sq.cell(8, 4, "=SUM($D$4:$D$7)")
    for row in sq.iter_rows(min_row=4, max_row=8, max_col=5):
        for cell in row:
            cell.font = Font(name=FONT, size=10, color=INK)
    for c in range(1, 5):
        sq.cell(8, c).font = Font(name=FONT, size=10, bold=True, color=INK)
    sq["A10"] = "Projected points of the players you have drafted:"
    sq["B10"] = f'=SUMIFS(Board!{E},Board!{F},"MINE")'
    sq["A10"].font = Font(name=FONT, size=10, color=INK)
    sq["B10"].font = Font(name=FONT, size=10, bold=True, color=ACCENT)
    for col, w in zip("ABCDE", [10, 10, 8, 12, 20]):
        sq.column_dimensions[col].width = w

    # ---------------------------------------------------------------- Guide --
    gd = wb.create_sheet("Guide")
    lines = [
        ("How to use this workbook", True),
        ("", False),
        ("1. Open the Board tab. It lists every draftable player, best first.", False),
        ("2. As each pick happens, set that player's Status using the yellow dropdown.", False),
        ("   GONE = someone else took him.  MINE = you took him.", False),
        ("3. VORP recalculates for everyone the moment you do.", False),
        ("4. Re-sort by VORP using the filter arrow on that column to reorder the board.", False),
        ("5. My Squad shows what you still need and the best available at each position.", False),
        ("", False),
        ("What VORP means", True),
        ("Points above the replacement-level player at the same position.", False),
        ("In Draft there is no budget, so every player costs exactly one pick. The only", False),
        ("question that matters is how many points he gives you over whoever you could", False),
        ("get at that position later. VORP is that number, and it is what to sort by.", False),
        ("A forward on 140 when the 16th forward gets 120 is worth less than a defender", False),
        ("on 125 when the 32nd defender gets 88.", False),
        ("", False),
        ("Things to know", True),
        ("Tier is a snapshot from when this file was generated and does not update.", False),
        ("It groups players within a position whose VORP started close together.", False),
        ("VORP and Best available DO update live.", False),
        ("Sorting is manual, because a self-sorting sheet needs array formulas that", False),
        ("do not survive being written by a script.", False),
        ("Projections are preseason estimates. See README.md for how they are built.", False),
        ("Needs Excel 2019 or Microsoft 365. The MINIFS function is not in older versions.", False),
    ]
    for i, (text, bold) in enumerate(lines, start=1):
        gd.cell(i, 1, text)
        gd.cell(i, 1).font = Font(name=FONT, size=12 if bold else 10,
                                  bold=bold, color=INK)
    gd.column_dimensions["A"].width = 92

    # Open on the Board, which is where all the work happens. Settings and Calc
    # are reference tabs and belong at the back.
    wb._sheets = [wb[name] for name in
                  ["Board", "My Squad", "Guide", "Calc", "Settings"]]
    wb.active = 0

    wb.save(path)
    return path
