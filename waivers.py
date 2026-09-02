"""In-season waiver dashboard: who to claim, and who to drop for him.

The draft board answered "who is worth a pick". This answers the question that
replaces it once the season starts, which is a different one:

    How many points does this free agent add to MY team next week, given who
    he would actually displace?

Ranking free agents by raw projection is the standard mistake. A 4.0-a-week
forward is a big add if your second forward is on 1.8 and worth nothing if he
is on 4.1. So every row here is scored against your own weakest startable
player at that position, and paired with the specific man to drop.

Claims are numbered because FPL processes waivers in priority order: if your
first choice is gone, the claim falls through to the second. That makes a long
shot at number one free, which is exactly why a just-arrived star belongs there
even when you expect to lose him.
"""

from __future__ import annotations

import json

from model import SQUAD_LIMITS, Player

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pickup Targets</title>
<style>
  :root{color-scheme:light dark;
    --surface:#fcfcfb;--plane:#f9f9f7;--sunk:#f0efec;
    --ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
    --grid:#e1e0d9;--rule:#c3c2b7;--border:rgba(11,11,11,0.10);
    --accent:#2a78d6;--good:#0ca30c;--warn:#fab219;--crit:#d03b3b}
  @media(prefers-color-scheme:dark){:root{
    --surface:#1a1a19;--plane:#0d0d0d;--sunk:#232322;
    --ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--rule:#383835;--border:rgba(255,255,255,0.10);
    --accent:#3987e5}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);
    font:14.5px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:1500px;margin:0 auto;padding:14px 16px 70px}
  .top{display:flex;align-items:center;gap:13px;flex-wrap:wrap;
    padding-bottom:12px;border-bottom:1px solid var(--grid);margin-bottom:14px}
  .lg{font-size:18px;font-weight:650;letter-spacing:-.01em}
  .chip{font-size:12px;padding:3px 10px;border-radius:20px;
    border:1px solid var(--rule);color:var(--ink-2);white-space:nowrap}
  .chip b{color:var(--ink)}
  .dot{width:7px;height:7px;border-radius:50%;display:inline-block;
    margin-right:6px;vertical-align:1px;background:var(--muted)}
  .live .dot{background:var(--good);animation:pulse 2s infinite}
  .err .dot{background:var(--crit)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .spacer{flex:1}
  button,select,input{font:inherit;font-size:13.5px;padding:6px 11px;
    border-radius:7px;background:var(--surface);color:var(--ink);
    border:1px solid var(--rule);cursor:pointer}
  button:hover{background:var(--sunk)}
  .card{background:var(--surface);border:1px solid var(--border);
    border-radius:10px;padding:14px 16px;margin-bottom:14px}
  .card h3{margin:0 0 4px;font-size:10.5px;letter-spacing:.09em;
    text-transform:uppercase;color:var(--muted);font-weight:700}
  .card .sub{font-size:12.5px;color:var(--muted);margin-bottom:11px}
  .cols{display:grid;grid-template-columns:1.7fr 1fr;gap:14px}
  @media(max-width:1100px){.cols{grid-template-columns:1fr}}

  /* claim rows */
  .claim{display:grid;grid-template-columns:34px 1fr auto;gap:11px;
    align-items:center;padding:9px 8px;border-bottom:1px solid var(--grid)}
  .claim:last-child{border-bottom:none}
  .claim.pin{background:color-mix(in srgb,var(--warn) 12%,transparent);
    border-radius:8px}
  .rank{font-size:19px;font-weight:700;color:var(--muted);text-align:center;
    font-variant-numeric:tabular-nums}
  .claim.pin .rank{color:var(--warn)}
  .nm{font-weight:650;font-size:15px}
  .sub2{font-size:12px;color:var(--ink-2);margin-top:2px}
  .drop{font-size:12px;color:var(--muted);margin-top:3px}
  .drop b{color:var(--ink-2)}
  .gain{text-align:right;font-variant-numeric:tabular-nums}
  .gain .g1{font-size:17px;font-weight:700}
  .gain .g2{font-size:11px;color:var(--muted)}
  .pos-good{color:var(--good)}.pos-bad{color:var(--crit)}
  .pinbtn{padding:2px 8px;font-size:11px;margin-left:6px}

  /* squad */
  .sq{display:grid;grid-template-columns:1fr auto auto;gap:9px;
    padding:5px 0;border-bottom:1px solid var(--grid);align-items:baseline;
    font-size:13.5px}
  .sq:last-child{border-bottom:none}
  .sq .sn{font-weight:600}
  .sq .sm{font-size:11px;color:var(--muted)}
  .sq .sv{font-variant-numeric:tabular-nums;font-weight:650}
  .sq.weak{background:color-mix(in srgb,var(--crit) 9%,transparent);
    border-radius:6px;padding-left:6px;padding-right:6px}
  .poshead{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
    color:var(--muted);font-weight:700;padding:9px 0 3px}
  .st{font-size:10.5px;font-variant-numeric:tabular-nums}
  .st.hi{color:var(--good)}.st.mid{color:var(--warn)}.st.lo{color:var(--crit);font-weight:700}
  .fdr{display:inline-flex;gap:2px;vertical-align:-1px;margin-left:5px}
  .fdr i{width:8px;height:8px;border-radius:2px;display:inline-block}
  .fdr .d1,.fdr .d2{background:#0ca30c}.fdr .d3{background:#c3c2b7}
  .fdr .d4{background:#ec835a}.fdr .d5{background:#d03b3b}
  .flag{display:inline-block;font-size:9.5px;padding:0 4px;border-radius:3px;
    border:1px solid var(--border);color:var(--muted);margin-left:3px}
  .flag.pen{border-color:var(--good);color:var(--good);font-weight:700}
  .flag.dc{border-color:var(--accent);color:var(--accent);font-weight:700}
  .flag.hurt{border-color:var(--crit);color:var(--crit);font-weight:700}
  .flag.new{border-color:var(--accent);color:var(--accent);font-weight:700}
  .tier{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;
    border-radius:9px;margin-left:5px;letter-spacing:.02em}
  .tier.hi{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
  .tier.mid{background:color-mix(in srgb,var(--warn) 20%,transparent);color:#8a6200}
  .tier.lo{background:color-mix(in srgb,var(--crit) 16%,transparent);color:var(--crit)}
  @media(prefers-color-scheme:dark){.tier.mid{color:var(--warn)}}
  .top1note{font-size:11.5px;color:var(--ink-2);margin-top:4px;font-style:italic}
  .needs{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
  .needchip{font-size:11.5px;padding:4px 10px;border-radius:8px;
    border:1px solid var(--rule);color:var(--ink-2)}
  .needchip b{color:var(--ink)}
  .needchip.gap{border-color:var(--crit);color:var(--crit)}
  .needchip.gap b{color:var(--crit)}
  .warnbar{background:color-mix(in srgb,var(--warn) 15%,transparent);
    border:1px solid var(--warn);border-radius:8px;padding:10px 14px;
    margin-bottom:13px;font-size:13.5px}
  .seg{display:flex;gap:4px}
  .seg button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
  .empty{padding:22px;text-align:center;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <span class="lg" id="lgName">Pickup Targets</span>
    <span class="chip" id="status"><span class="dot"></span><span id="statusTxt">loading</span></span>
    <span class="chip" id="chipGw">GW -</span>
    <span class="chip" id="chipTeam">-</span>
    <span class="spacer"></span>
    <input id="q" placeholder="Search a player to pin" style="width:200px">
    <div class="seg" id="posSeg"></div>
  </div>

  __BANNER__

  <div class="cols">
    <div>
      <div class="card">
        <h3>Pickup priority</h3>
        <div class="sub">Claims process in order. If number one is already taken
          by another manager, the claim falls through to number two automatically
          - so the best player available costs nothing to rank first, even if
          he's likely to get sniped. Gain is expected points per week versus
          your weakest <em>starter</em> at that position (beating your bench
          changes nothing), already discounted for how likely each player is to
          actually start.</div>
        <div class="needs" id="needs"></div>
        <div id="claims"></div>
      </div>
    </div>

    <div>
      <div class="card">
        <h3>Your squad <span id="sqCount" style="color:var(--ink-2)"></span></h3>
        <div class="sub">Red rows are your weakest at each position, which is
          who a claim would replace.</div>
        <div id="squad"></div>
      </div>
    </div>
  </div>
</div>

<script>
const PLAYERS = __DATA__;
const LIMITS  = __LIMITS__;
const MY_IDS  = new Set(__MY_IDS__);
const GW      = __GW__;
const POS = ["GKP","DEF","MID","FWD"];
const STARTERS = {GKP:1,DEF:4,MID:4,FWD:2};

let owned = new Set(__OWNED__);
let mine  = new Set(__MINE__);
let pinned = new Set();
let posFilter = null;
const byId = {}; PLAYERS.forEach(p=>byId[p.i]=p);

/* pins survive a refresh via the URL, nothing else is stored */
function savePins(){ history.replaceState(null,"","#pin="+[...pinned].join(".")); }
function loadPins(){
  const m=/pin=([\d.]+)/.exec(location.hash);
  if(m) m[1].split(".").filter(Boolean).forEach(x=>pinned.add(parseInt(x)));
}

function mySquad(){ return PLAYERS.filter(p=>mine.has(p.i)); }

/* The man a new signing displaces: your weakest STARTER at that position, not
   your weakest player. Beating your bench changes nothing. */
function replacement(pos){
  const g = mySquad().filter(p=>p.pos===pos).sort((a,b)=>b.pw-a.pw);
  if(!g.length) return 0;
  const n = Math.min(STARTERS[pos]||3, g.length);
  return g[n-1].pw;
}
/* Name of the weakest starter, which is the one the gain is measured against.
   Distinct from weakestAt(), who is simply the man you would drop. */
function replName(pos){
  const g = mySquad().filter(p=>p.pos===pos).sort((a,b)=>b.pw-a.pw);
  if(!g.length) return "nobody";
  const n = Math.min(STARTERS[pos]||3, g.length);
  return g[n-1].n;
}
function weakestAt(pos){
  const g = mySquad().filter(p=>p.pos===pos).sort((a,b)=>a.pw-b.pw);
  return g[0]||null;
}

function stCls(r){ return r>=0.85?"hi":r>=0.5?"mid":"lo"; }
/* Starter confidence: is this a nailed starter, a rotation risk, or a bench
   player, factoring in injury/suspension availability alongside start rate. */
function tier(p){
  if(p.f&&p.f.includes("NEW")) return {label:"New / unproven",cls:"mid"};
  if(p.ch<0.75) return {label:"Doubtful",cls:"lo"};
  if(p.sr>=0.85) return {label:"Confirmed starter",cls:"hi"};
  if(p.sr>=0.5)  return {label:"Rotation risk",cls:"mid"};
  return {label:"Bench / fringe",cls:"lo"};
}
function tierBadge(p){ const t=tier(p); return `<span class="tier ${t.cls}">${t.label}</span>`; }
function fdrHtml(p){
  if(!p.fdr||!p.fdr.length) return "";
  return `<span class="fdr" title="next fixtures, 1 easy to 5 hard">`+
    p.fdr.map(d=>`<i class="d${d}"></i>`).join("")+`</span>`;
}
function flags(p){
  return (p.f||[]).map(f=>{
    const c=f==="PENS"?"pen":f==="DEFCON"?"dc":f==="NEW"?"new"
      :/injur|doubt|suspend|unavail|fit|not in squad/.test(f)?"hurt":"";
    return `<span class="flag ${c}">${f}</span>`;
  }).join("");
}

function render(){
  const repl={}; POS.forEach(pos=>repl[pos]=replacement(pos));

  // Needs strip: how many starting slots at each position are filled by a
  // confirmed starter, versus a rotation risk or an empty slot outright.
  document.getElementById("needs").innerHTML = POS.map(pos=>{
    const g = mySquad().filter(p=>p.pos===pos).sort((a,b)=>b.pw-a.pw);
    const need = STARTERS[pos]||3;
    const locked = g.slice(0,need).filter(p=>tier(p).cls==="hi").length;
    const gap = locked < need;
    return `<span class="needchip ${gap?"gap":""}">${pos} <b>${locked}/${need}</b> locked</span>`;
  }).join("");

  let free = PLAYERS.filter(p=>!owned.has(p.i));
  if(posFilter) free = free.filter(p=>p.pos===posFilter);

  const rows = free.map(p=>({
    p, gain: p.pw - (repl[p.pos]||0), pinned: pinned.has(p.i)
  }));
  // Pinned first, then by what they actually add (pw is already discounted
  // for start/rotation risk, so this doubles as "most valuable given need").
  rows.sort((a,b)=> (b.pinned?1:0)-(a.pinned?1:0) || b.gain-a.gain);
  const top = rows.slice(0,14);

  document.getElementById("claims").innerHTML = top.length ? top.map((r,i)=>{
    const p=r.p, drop=weakestAt(p.pos);
    const cls = r.gain>0?"pos-good":"pos-bad";
    const top1 = (i===0 && !r.pinned)
      ? `<div class="top1note">Free claim - if he's already gone this falls
          through to #2 automatically, so there's no downside to aiming high.</div>`
      : "";
    return `<div class="claim ${r.pinned?"pin":""}">
      <div class="rank">${i+1}</div>
      <div>
        <div class="nm">${p.n}${tierBadge(p)}
          <button class="pinbtn" data-pin="${p.i}">${r.pinned?"unpin":"pin"}</button>
        </div>
        <div class="sub2">${p.pos} &middot; ${p.tm} &middot;
          <span class="st ${stCls(p.sr)}">${Math.round(p.sr*100)}% start rate</span>
          &middot; ${p.pw.toFixed(1)} pts/wk &middot; form ${p.fm.toFixed(1)}
          ${flags(p)}${fdrHtml(p)}</div>
        <div class="drop">upgrades on <b>${replName(p.pos)}</b>
          (${(repl[p.pos]||0).toFixed(1)} pts/wk, your weakest starting ${p.pos})
          &middot; roster spot from <b>${drop?drop.n:"-"}</b></div>
        ${top1}
      </div>
      <div class="gain">
        <div class="g1 ${cls}">${r.gain>0?"+":""}${r.gain.toFixed(1)}</div>
        <div class="g2">pts/week</div>
      </div>
    </div>`;
  }).join("") : `<div class="empty">No free agents match.</div>`;

  // squad, grouped by position, weakest flagged
  let html="";
  for(const pos of POS){
    const g = mySquad().filter(p=>p.pos===pos).sort((a,b)=>b.pw-a.pw);
    html += `<div class="poshead">${pos} ${g.length}/${LIMITS[pos]}</div>`;
    if(!g.length){ html += `<div class="sq"><span class="sm">none</span></div>`; continue; }
    const w = weakestAt(pos);
    for(const p of g){
      html += `<div class="sq ${w&&p.i===w.i?"weak":""}">
        <div><div class="sn">${p.n}${tierBadge(p)}</div>
          <div class="sm">${p.tm} &middot;
            <span class="st ${stCls(p.sr)}">${Math.round(p.sr*100)}% start</span>
            ${flags(p)}${fdrHtml(p)}</div></div>
        <div class="sv">${p.pw.toFixed(1)}</div>
        <div class="sm">${p.tp} pts</div>
      </div>`;
    }
  }
  document.getElementById("squad").innerHTML = html;
  document.getElementById("sqCount").textContent = `${mine.size}/15`;
  savePins();
}

document.addEventListener("click",e=>{
  const b=e.target.closest("[data-pin]"); if(!b) return;
  const id=parseInt(b.dataset.pin);
  pinned.has(id)?pinned.delete(id):pinned.add(id);
  render();
});
const q=document.getElementById("q");
q.addEventListener("keydown",e=>{
  if(e.key!=="Enter") return;
  const t=q.value.trim().toLowerCase(); if(!t) return;
  const hit=PLAYERS.filter(p=>!owned.has(p.i)&&p.s.includes(t))
    .sort((a,b)=>b.pw-a.pw)[0];
  if(hit){ pinned.add(hit.i); q.value=""; render(); }
  else { q.value=""; alert("No free agent matches that name."); }
});
const seg=document.getElementById("posSeg");
seg.innerHTML=[["All",""],...POS.map(p=>[p,p])]
  .map(([l,v])=>`<button data-v="${v}" class="${v===""?"on":""}">${l}</button>`).join("");
seg.addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b) return;
  posFilter=b.dataset.v||null;
  [...seg.children].forEach(c=>c.classList.toggle("on",c===b));
  render();
});

function setStatus(k,t){
  document.getElementById("status").className="chip "+k;
  document.getElementById("statusTxt").textContent=t;
}

/* Ownership changes as rivals claim players, so keep it current. */
async function poll(){
  try{
    const r=await fetch("/api/choices",{cache:"no-store"});
    const d=await r.json();
    const nowOwned=new Set(), nowMine=new Set();
    for(const s of (d.element_status||[])){
      if(s.owner==null) continue;
      nowOwned.add(s.element);
      if(MY_IDS.has(s.owner)) nowMine.add(s.element);
    }
    if(nowOwned.size){ owned=nowOwned; if(nowMine.size) mine=nowMine; render(); }
    setStatus("live",`live · ${owned.size} owned`);
  }catch(e){ setStatus("err","connection lost, retrying"); }
}
async function pollLeague(){
  try{
    const d=await (await fetch("/api/league",{cache:"no-store"})).json();
    if(d.league&&d.league.name) document.getElementById("lgName").textContent=d.league.name;
    const me=(d.standings||[]).find(s=>MY_IDS.has(s.league_entry));
    if(me) document.getElementById("chipTeam").innerHTML =
      `rank <b>${me.rank}</b> &middot; <b>${me.total}</b> pts`;
  }catch(e){}
}

loadPins();
document.getElementById("chipGw").innerHTML = `GW <b>${GW}</b> played`;
render();
setStatus("live","connecting");
poll(); pollLeague();
setInterval(poll, 15000);
setInterval(pollLeague, 120000);
</script>
</body>
</html>
"""


def build(players: list[Player], my_ids: set[int], owned: set[int],
          mine: set[int], gw: int, sample: bool = False) -> str:
    rows = []
    for p in players:
        rows.append({
            "i": p.draft_id, "n": p.name, "pos": p.pos, "tm": p.team_short,
            "pw": round(p.proj_week, 2), "sr": round(p.start_rate, 2),
            "ch": round(p.chance, 2), "fm": round(p.form, 1),
            "tp": int(p.season_points),
            "fdr": p.fdr[:5], "f": p.flags[:3],
            "s": f"{p.name} {p.full_name}".lower(),
        })

    banner = ""
    if sample:
        banner = ('<div class="warnbar"><b>Sample data.</b> Not real players. '
                  'Run <code>py draft.py --deep --refresh fetch</code> first.</div>')

    return (TEMPLATE
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False))
            .replace("__LIMITS__", json.dumps(SQUAD_LIMITS))
            .replace("__MY_IDS__", json.dumps(sorted(my_ids)))
            .replace("__OWNED__", json.dumps(sorted(owned)))
            .replace("__MINE__", json.dumps(sorted(mine)))
            .replace("__GW__", str(gw))
            .replace("__BANNER__", banner))
