"""The live draft dashboard.

One template serves two modes:

  LIVE     served from localhost by serve.py. Polls your league's own draft
           record every few seconds, so picks appear without you touching
           anything. It also derives the draft order from round one, which
           means your snake slot is detected rather than guessed.

  MANUAL   written to a file by `export`. Same layout and same maths, but you
           mark picks by typing names. Used when there is no league to watch,
           or as a backup if the API goes down mid-draft.

The maths lives in the browser because it has to recompute on every single
pick: replacement level moves, so VORP moves, so tiers and the recommendation
move with them. Python does the part that never changes during a draft, which
is the projections.
"""

from __future__ import annotations

import json

from model import SQUAD_LIMITS, TYPICAL_STARTERS, Player

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Draft Dashboard</title>
<style>
  :root {
    color-scheme: light dark;
    --surface:#fcfcfb; --plane:#f9f9f7; --sunk:#f0efec;
    --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --rule:#c3c2b7; --border:rgba(11,11,11,0.10);
    --accent:#2a78d6; --good:#0ca30c; --warn:#fab219; --crit:#d03b3b;
    --t1:#184f95; --t2:#256abf; --t3:#3987e5; --t4:#6da7ec; --t5:#86b6ef;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface:#1a1a19; --plane:#0d0d0d; --sunk:#232322;
      --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --rule:#383835; --border:rgba(255,255,255,0.10);
      --accent:#3987e5;
      --t1:#86b6ef; --t2:#6da7ec; --t3:#3987e5; --t4:#2a78d6; --t5:#256abf;
    }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);
       font:14.5px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:1500px;margin:0 auto;padding:14px 16px 70px}

  /* ---------- top bar ---------- */
  .top{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
       padding-bottom:12px;border-bottom:1px solid var(--grid);margin-bottom:14px}
  .lg-name{font-size:18px;font-weight:650;letter-spacing:-0.01em}
  .chip{font-size:12px;padding:3px 10px;border-radius:20px;
        border:1px solid var(--rule);color:var(--ink-2);white-space:nowrap}
  .chip b{color:var(--ink)}
  .dot{width:7px;height:7px;border-radius:50%;display:inline-block;
       margin-right:6px;vertical-align:1px;background:var(--muted)}
  .live .dot{background:var(--good);animation:pulse 2s infinite}
  .stale .dot{background:var(--warn)}
  .err .dot{background:var(--crit)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .spacer{flex:1}
  button,select,input[type=search]{
    font:inherit;font-size:13.5px;padding:6px 11px;border-radius:7px;
    background:var(--surface);color:var(--ink);
    border:1px solid var(--rule);cursor:pointer}
  button:hover{background:var(--sunk)}

  /* ---------- clock strip ---------- */
  .clock{display:flex;align-items:center;gap:16px;flex-wrap:wrap;
         border-radius:10px;padding:11px 16px;margin-bottom:14px;
         background:var(--surface);border:1px solid var(--border)}
  .clock.mine{background:color-mix(in srgb,var(--good) 14%,transparent);
              border-color:var(--good)}
  .clock.soon{background:color-mix(in srgb,var(--warn) 15%,transparent);
              border-color:var(--warn)}
  .clock .lab{font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
              color:var(--muted);font-weight:700}
  .clock .val{font-size:17px;font-weight:650}
  .clock .big{font-size:23px;font-weight:700;letter-spacing:-.02em}

  /* ---------- layout ---------- */
  .cols{display:grid;grid-template-columns:1.55fr 1fr;gap:14px;margin-bottom:14px}
  @media(max-width:1050px){.cols{grid-template-columns:1fr}}
  .card{background:var(--surface);border:1px solid var(--border);
        border-radius:10px;padding:14px 16px}
  .card h3{margin:0 0 10px;font-size:10.5px;letter-spacing:.09em;
           text-transform:uppercase;color:var(--muted);font-weight:700}

  /* ---------- the pick ---------- */
  #rec{border-left:3px solid var(--accent)}
  #rec .nm{font-size:31px;font-weight:700;letter-spacing:-.025em;line-height:1.1}
  #rec .meta{color:var(--ink-2);font-size:13.5px;margin-top:5px}
  #rec .why{margin-top:9px;font-size:13.5px;color:var(--ink-2)}
  #rec .why b{color:var(--ink);font-weight:650}
  #rec .news{margin-top:6px;font-size:13px;color:var(--crit)}
  .alts{margin-top:12px;padding-top:11px;border-top:1px solid var(--grid);
        display:flex;gap:8px;flex-wrap:wrap}
  .alt{flex:1 1 150px;border:1px solid var(--border);border-radius:8px;
       padding:7px 10px;background:var(--plane);cursor:pointer}
  .alt:hover{border-color:var(--accent)}
  .alt .an{font-weight:600;font-size:14px}
  .alt .am{font-size:11.5px;color:var(--muted);margin-top:1px}

  /* ---------- roster ---------- */
  .need-row{display:flex;justify-content:space-between;align-items:baseline;
            padding:5px 0;border-bottom:1px solid var(--grid);font-size:13.5px}
  .need-row:last-child{border-bottom:none}
  .need-row .p{font-weight:650;width:38px}
  .need-row .c{font-variant-numeric:tabular-nums;color:var(--ink-2)}
  .need-row .who{flex:1;color:var(--ink-2);font-size:12.5px;
                 padding-left:10px;text-align:right}
  .need-row.full .c{color:var(--good);font-weight:650}
  .need-row.urgent .c{color:var(--crit);font-weight:650}

  /* ---------- position columns ---------- */
  .pos4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
  @media(max-width:1050px){.pos4{grid-template-columns:repeat(2,1fr)}}
  @media(max-width:620px){.pos4{grid-template-columns:1fr}}
  .pcol h4{margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:.05em;
           display:flex;justify-content:space-between;align-items:baseline}
  .pcol h4 .n{color:var(--muted);font-weight:600;font-size:11px}
  .pr{display:grid;grid-template-columns:1fr auto;gap:6px;padding:5px 7px;
      border-radius:6px;cursor:pointer;align-items:baseline}
  .pr:hover{background:var(--sunk)}
  .pr .n1{font-weight:600;font-size:13.5px;overflow:hidden;
          text-overflow:ellipsis;white-space:nowrap}
  .pr .n2{font-size:11px;color:var(--muted)}
  .pr .v{font-variant-numeric:tabular-nums;font-weight:650;font-size:13px;
         text-align:right}
  .pr .s{font-size:10.5px;text-align:right}
  .risk-hi{color:var(--crit);font-weight:700}
  .risk-lo{color:var(--good)}
  .risk-mid{color:var(--muted)}
  .tierbreak{height:1px;background:var(--rule);margin:5px 4px;position:relative}
  .tierbreak::after{content:attr(data-l);position:absolute;right:0;top:-7px;
    font-size:9px;color:var(--muted);background:var(--surface);padding:0 4px;
    letter-spacing:.06em}
  .dim{opacity:.45}

  /* ---------- runs ---------- */
  .runs{display:flex;gap:10px;flex-wrap:wrap}
  .run{flex:1 1 150px;border:1px solid var(--border);border-radius:8px;
       padding:8px 11px;background:var(--plane)}
  .run .rp{font-size:11px;color:var(--muted);letter-spacing:.06em;font-weight:700}
  .run .rv{font-size:16px;font-weight:650;font-variant-numeric:tabular-nums}
  .run .rb{height:4px;background:var(--grid);border-radius:2px;margin-top:5px;
           overflow:hidden}
  .run .rf{height:100%;border-radius:2px;background:var(--accent)}
  .run.hot{border-color:var(--crit)}
  .run.hot .rf{background:var(--crit)}
  .run.hot .rv{color:var(--crit)}

  /* ---------- log ---------- */
  #logRows{max-height:280px;overflow-y:auto}
  .lg{display:grid;grid-template-columns:46px 1fr 38px 40px 100px;gap:8px;
      padding:4px 0;font-size:13px;border-bottom:1px solid var(--grid);
      align-items:baseline}
  .lg:last-child{border-bottom:none}
  .lg .rd{color:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}
  .lg .tm{color:var(--muted);font-size:11.5px;text-align:right;overflow:hidden;
          text-overflow:ellipsis;white-space:nowrap}
  .lg.me{background:color-mix(in srgb,var(--good) 10%,transparent)}
  .lg.me .tm{color:var(--good);font-weight:700}
  .lg.fresh{animation:flash 1.6s ease-out}
  @keyframes flash{0%{background:color-mix(in srgb,var(--accent) 30%,transparent)}
                   100%{background:transparent}}
  .rsep{font-size:10px;letter-spacing:.08em;text-transform:uppercase;
        color:var(--muted);padding:7px 0 3px;font-weight:700}

  .warnbar{background:color-mix(in srgb,var(--warn) 16%,transparent);
    border:1px solid var(--warn);border-radius:8px;padding:10px 14px;
    margin-bottom:13px;font-size:13.5px}
  .flag{display:inline-block;font-size:9.5px;padding:0 4px;border-radius:3px;
        border:1px solid var(--border);color:var(--muted);margin-left:3px}
  .flag.pen{border-color:var(--good);color:var(--good);font-weight:700}
  .flag.dc{border-color:var(--accent);color:var(--accent);font-weight:700}
  .flag.hurt{border-color:var(--crit);color:var(--crit);font-weight:700}
  .hide{display:none !important}
  .slgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:8px}
  .slcard{border:1px solid var(--border);border-radius:8px;padding:8px 11px;
          background:var(--plane);cursor:pointer}
  .slcard:hover{border-color:var(--accent)}
  .slcard.avoid{border-color:var(--crit);opacity:.75}
  .slcard .sh{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
  .slcard .sn{font-weight:650;font-size:14px}
  .slcard .sv{font-variant-numeric:tabular-nums;font-size:12.5px;color:var(--muted)}
  .slcard .sd{font-size:11.5px;color:var(--ink-2);margin-top:3px;line-height:1.35}
  .slcard .sm{font-size:11px;color:var(--muted);margin-top:3px}
  /* fixture strip: five squares, one per upcoming match */
  .fdr{display:inline-flex;gap:2px;vertical-align:-1px;margin-left:5px}
  .fdr i{width:9px;height:9px;border-radius:2px;display:inline-block}
  .fdr .d1,.fdr .d2{background:#0ca30c}
  .fdr .d3{background:#c3c2b7}
  .fdr .d4{background:#ec835a}
  .fdr .d5{background:#d03b3b}
  .stp{font-size:10.5px;font-variant-numeric:tabular-nums}
  .stp.lo{color:var(--crit);font-weight:700}
  .stp.mid{color:var(--warn)}
  .stp.hi{color:var(--muted)}
  .sl{display:inline-block;font-size:9.5px;font-weight:700;padding:0 4px;
      border-radius:3px;margin-left:4px;letter-spacing:.03em}
  .sl.t1{background:var(--good);color:#fff}
  .sl.t2{background:var(--accent);color:#fff}
  .sl.t0{background:var(--crit);color:#fff}
  .slnote{font-size:12.5px;color:var(--ink-2);margin-top:7px;
          padding:7px 10px;border-radius:7px;background:var(--plane);
          border-left:2px solid var(--accent)}
  .bal{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px}
  .balp{flex:1 1 90px;border:1px solid var(--border);border-radius:7px;
        padding:6px 9px;background:var(--plane);font-size:12px}
  .balp .bl{color:var(--muted);font-weight:700;font-size:10.5px}
  .balp .bv{font-size:13px;font-weight:650}
  .balp.behind{border-color:var(--warn)}
  .balp.behind .bv{color:var(--warn)}
  #manual{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:13px}
  #q{flex:1 1 240px}
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <span class="lg-name" id="lgName">Draft Dashboard</span>
    <span class="chip" id="status"><span class="dot"></span><span id="statusTxt">starting</span></span>
    <span class="chip" id="chipRound">round -</span>
    <span class="chip" id="chipSlot">slot -</span>
    <span class="spacer"></span>
    <select id="teams" title="Managers in the league"></select>
    <select id="slot" title="Your pick in round 1"></select>
    <button id="undo" class="hide">Undo</button>
    <button id="reset">Reset</button>
  </div>

  __BANNER__

  <div id="manual" class="hide">
    <input type="search" id="q" placeholder="Type a name, Enter = drafted by someone, Shift+Enter = yours" autocomplete="off">
    <span style="font-size:12.5px;color:var(--muted)">manual mode</span>
  </div>

  <div class="clock" id="clock">
    <div><div class="lab">On the clock</div><div class="val" id="onClock">-</div></div>
    <div style="width:1px;height:30px;background:var(--grid)"></div>
    <div><div class="lab">Your next pick</div><div class="big" id="myNext">-</div></div>
    <div style="width:1px;height:30px;background:var(--grid)"></div>
    <div><div class="lab">Picks until then</div><div class="big" id="untilMe">-</div></div>
    <span class="spacer"></span>
    <div style="text-align:right"><div class="lab">Board</div>
      <div class="val" id="boardLeft">-</div></div>
  </div>

  <div class="cols">
    <div class="card" id="rec"></div>
    <div class="card">
      <h3>Your squad <span id="squadCount" style="color:var(--ink-2)"></span></h3>
      <div id="needs"></div>
      <div class="bal" id="balance"></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:14px">
    <h3>Best available by position <span style="text-transform:none;letter-spacing:0;font-weight:400">
      &middot; click any name to draft him to your squad</span></h3>
    <div class="pos4" id="pos4"></div>
  </div>

  <div class="card" style="margin-bottom:14px" id="slPanel">
    <h3>Sleeper watch <span style="text-transform:none;letter-spacing:0;font-weight:400">
      &middot; from your research, still available &middot; click to draft</span></h3>
    <div class="slgrid" id="slRows"></div>
  </div>

  <div class="card" style="margin-bottom:14px">
    <h3>Position runs <span style="text-transform:none;letter-spacing:0;font-weight:400">
      &middot; how many have gone in the last 10 picks, and how thin it is getting</span></h3>
    <div class="runs" id="runs"></div>
  </div>

  <div class="card">
    <h3>Draft log <span id="logCount" style="color:var(--ink-2)"></span></h3>
    <div id="logRows"></div>
  </div>
</div>

<script>
const PLAYERS   = __DATA__;
const STARTERS  = __STARTERS__;
const LIMITS    = __LIMITS__;
const LOOKAHEAD = __LOOKAHEAD__;
const LIVE      = __LIVE__;
const MY_IDS    = new Set(__MY_IDS__);
const POS = ["GKP","DEF","MID","FWD"];
const ROUNDS = POS.reduce((s,p)=>s+LIMITS[p],0);

let nTeams = __NTEAMS__;
let slot   = __SLOT__;
let slotLocked = false;      // true once derived from real draft data
let picks  = [];             // [{i,mine,rd,pk,team}] in draft order
let gone = new Set(), mine = new Set();
let entriesById = {};        // entry id -> team name
let order = [];              // entry ids in round-1 pick order
let lastCount = -1, freshIds = new Set();

const byId = {}; PLAYERS.forEach(p => byId[p.i] = p);

function rebuild(){ gone.clear(); mine.clear();
  for (const p of picks) (p.mine?mine:gone).add(p.i); }

/* ================= state in the URL, for manual mode ================= */
function saveState(){
  if (LIVE) return;                       // live mode's truth is the API
  const p = picks.map(x=>x.i+(x.mine?"*":"")).join(".");
  history.replaceState(null,"",`#p=${p}&t=${nTeams}&s=${slot}`);
}
function loadState(){
  const h = location.hash.slice(1); if(!h) return;
  for (const part of h.split("&")){
    const [k,v] = part.split("=");
    if (k==="t") nTeams = parseInt(v)||nTeams;
    if (k==="s") slot   = parseInt(v)||slot;
    if (k==="p" && v) v.split(".").filter(Boolean).forEach(tok=>{
      const m = tok.endsWith("*"); const id = parseInt(m?tok.slice(0,-1):tok);
      if(!isNaN(id)) picks.push({i:id,mine:m});
    });
  }
  rebuild();
}

/* ================= snake schedule ================= */
function snakePicks(){
  const out=[];
  for(let r=0;r<ROUNDS;r++)
    out.push(r%2===0 ? r*nTeams+slot : r*nTeams+(nTeams-slot+1));
  return out;
}
function pickInfo(){
  const made = picks.length;
  const up = snakePicks().filter(p=>p>made);
  if(!up.length) return {next:0,following:0,gap:0,untilMe:0};
  return {next:up[0], following:up[1]||up[0],
          gap:Math.max(0,(up[1]||up[0])-up[0]-1), untilMe:up[0]-made-1};
}
/* Whose turn it is, from the round-one order once we know it. */
function onTheClock(){
  const idx = picks.length;                       // 0-based overall pick
  const r = Math.floor(idx/nTeams), s = idx%nTeams;
  const seat = r%2===0 ? s : nTeams-1-s;
  // Your own slot is known even when that seat has not picked yet.
  if(slotLocked && seat === slot-1) return [...MY_IDS][0];
  return (order[seat] != null) ? order[seat] : null;
}

/* ================= model ================= */
function available(){ return PLAYERS.filter(p=>!gone.has(p.i)&&!mine.has(p.i)); }

function recompute(){
  const av = available(), repl = {};
  for(const pos of POS){
    const g = av.filter(p=>p.pos===pos).sort((a,b)=>b.proj-a.proj);
    if(!g.length){ repl[pos]=0; continue; }
    // Replacement = best player who starts for nobody, so one past the
    // league-wide starter count at that position.
    const i = Math.min(Math.round(STARTERS[pos]*nTeams), g.length-1);
    repl[pos] = g[i].proj;
  }
  PLAYERS.forEach(p=>p.vorp = p.proj - (repl[p.pos]||0));
  for(const pos of POS){
    const g = av.filter(p=>p.pos===pos).sort((a,b)=>b.vorp-a.vorp);
    let t=1; g.forEach((p,i)=>{ if(i>0 && g[i-1].vorp-p.vorp>8) t++; p.tier=t; });
  }
  return repl;
}
function needs(){
  const c={GKP:0,DEF:0,MID:0,FWD:0};
  PLAYERS.forEach(p=>{ if(mine.has(p.i)) c[p.pos]++; });
  const n={}; POS.forEach(p=>n[p]=LIMITS[p]-c[p]);
  return {counts:c,need:n};
}
function survival(av,gap){
  const out={};
  if(gap<=0){ av.forEach(p=>out[p.i]=1); return out; }
  const ord = av.slice().sort((a,b)=>a.adp-b.adp);
  const s = Math.max(2,0.32*gap);
  ord.forEach((p,k)=>{
    const z = Math.max(-40,Math.min(40,(gap-k)/s));
    out[p.i] = 1 - 1/(1+Math.exp(-z));
  });
  return out;
}
function expectedNext(av,surv,pos){
  const c = av.filter(p=>p.pos===pos).sort((a,b)=>b.vorp-a.vorp).slice(0,40);
  let e=0,none=1;
  for(const p of c){ const s=surv[p.i]||0; e+=p.vorp*s*none; none*=(1-s);
                     if(none<1e-4) break; }
  return e;
}
function rank(av,key){
  const m={}; av.slice().sort(key).forEach((p,i)=>m[p.i]=i+1); return m;
}
function recommend(){
  const {need}=needs(), av=available();
  const elig = av.filter(p=>need[p.pos]>0);
  if(!elig.length) return [];
  const {gap}=pickInfo(), surv=survival(av,gap), en={};
  POS.forEach(p=>{ if(need[p]>0) en[p]=expectedNext(av,surv,p); });
  const vR = rank(av,(a,b)=>b.vorp-a.vorp), aR = rank(av,(a,b)=>a.adp-b.adp);
  const out = elig.map(p=>{
    const gain = p.vorp-(en[p.pos]||0);
    // Best-available is the baseline; scarcity only tilts it. Drafting on
    // gain alone tested worse than plain VORP, hence the low weight.
    let score = (p.vorp + LOOKAHEAD*gain) * (1+0.02*(need[p.pos]-1));
    return {p,score,gain,survive:surv[p.i]||0,vorpRank:vR[p.i],adpRank:aR[p.i]};
  });
  out.sort((a,b)=>b.score-a.score);
  return out;
}
function whyText(e,need){
  const w=[];
  if(e.gain>12) w.push(`<b>${e.gain.toFixed(0)} pts</b> better than the next ${e.p.pos} you'd get`);
  if(e.survive<0.30) w.push(`only <b>${(e.survive*100).toFixed(0)}%</b> to last to your next pick`);
  else if(e.survive>0.80&&e.gain<12) w.push(`<b>${(e.survive*100).toFixed(0)}%</b> to still be there, you can wait`);
  const sl=e.adpRank-e.vorpRank;
  if(sl>12) w.push(`market has him <b>${sl}</b> spots lower than your board`);
  else if(sl<-12) w.push(`market rates him <b>${-sl}</b> higher than your board`);
  if(e.p.f.includes("PENS")) w.push("takes <b>penalties</b>");
  if(e.p.f.includes("DEFCON")) w.push("high <b>defensive contribution</b>");
  if(need[e.p.pos]>=3) w.push(`you still need <b>${need[e.p.pos]} ${e.p.pos}</b>`);
  return w;
}
function fdrHtml(p){
  if(!p.fdr||!p.fdr.length) return "";
  return `<span class="fdr" title="next ${p.fdr.length} fixtures, 1 easy to 5 hard">`
    + p.fdr.map(d=>`<i class="d${d}"></i>`).join("") + `</span>`;
}
function startHtml(p){
  if(p.st==null) return "";
  const c = p.st<0.55?"lo":p.st<0.8?"mid":"hi";
  return `<span class="stp ${c}" title="estimated chance he starts a given week">`
    + `${Math.round(p.st*100)}% start</span>`;
}
function slHtml(p){
  if(!p.sl) return "";
  return `<span class="sl t${p.sl.tier}" title="${p.sl.note}">${p.sl.tag}</span>`;
}
function flags(p){
  return p.f.map(f=>{
    const c = f==="PENS"?"pen" : f==="DEFCON"?"dc"
      : /injur|doubt|suspend|unavail|fit|not in squad/.test(f)?"hurt":"";
    return `<span class="flag ${c}">${f}</span>`;
  }).join("");
}

/* ================= render ================= */
function render(){
  recompute();
  const {counts,need}=needs(), av=available(), pi=pickInfo();
  const rec=recommend(), surv=survival(av,pi.gap);

  // The DRAFT's position, not yours. Your own next pick lives in the clock
  // strip; mixing the two here read as a contradiction.
  const overallNext = picks.length + 1;
  document.getElementById("chipRound").innerHTML =
    `round <b>${Math.min(ROUNDS, Math.ceil(overallNext/nTeams))}</b>`
    + ` &middot; pick <b>${overallNext}</b> of ${ROUNDS*nTeams}`;
  document.getElementById("chipSlot").innerHTML =
    `slot <b>${slot}</b>${slotLocked?" (detected)":""}`;
  document.getElementById("boardLeft").textContent = `${av.length} left`;

  // clock strip
  const clk=document.getElementById("clock");
  const oc=onTheClock();
  document.getElementById("onClock").textContent =
    oc!=null ? (MY_IDS.has(oc)?"YOU":(entriesById[oc]||"manager "+oc))
             : (picks.length?"(seat not seen yet)":(LIVE?"waiting for draft":"-"));
  document.getElementById("myNext").textContent = pi.next?("#"+pi.next):"-";
  document.getElementById("untilMe").textContent =
    pi.untilMe<=0?"NOW":pi.untilMe;
  clk.classList.toggle("mine", pi.untilMe<=0);
  clk.classList.toggle("soon", pi.untilMe>0 && pi.untilMe<=2);

  // the pick
  const box=document.getElementById("rec");
  if(!rec.length){
    box.innerHTML=`<h3>Squad complete</h3><div class="nm">All 15 filled</div>`;
  } else {
    const t=rec[0], w=whyText(t,need);
    box.innerHTML = `<h3>Take now</h3>
      <div class="nm">${t.p.n}</div>
      <div class="meta">${t.p.pos} &middot; ${t.p.tm||t.p.t} &middot;
        ${t.p.proj} projected &middot; VORP ${t.p.vorp>0?"+":""}${t.p.vorp.toFixed(1)}
        &middot; market rank ${t.p.adp===9999?"unranked":t.p.adp}
        ${flags(t.p)}${slHtml(t.p)}</div>
      <div class="meta">${startHtml(t.p)} &middot; next 5 ${fdrHtml(t.p)}</div>
      ${w.length?`<div class="why">${w.join(" &middot; ")}</div>`:""}
      ${t.p.news?`<div class="news">${t.p.news}</div>`:""}
      ${t.p.sl?`<div class="slnote"><b>${t.p.sl.tag}:</b> ${t.p.sl.note}</div>`:""}
      <div class="alts">${rec.slice(1,4).map(e=>
        `<div class="alt" data-i="${e.p.i}">
           <div class="an">${e.p.n}</div>
           <div class="am">${e.p.pos} &middot; VORP ${e.p.vorp>0?"+":""}${e.p.vorp.toFixed(0)}
             &middot; ${(e.survive*100).toFixed(0)}% to last</div></div>`).join("")}</div>`;
  }

  // squad
  document.getElementById("squadCount").textContent = `${mine.size}/15`;
  document.getElementById("needs").innerHTML = POS.map(pos=>{
    const held = PLAYERS.filter(p=>mine.has(p.i)&&p.pos===pos).map(p=>p.n);
    const left = need[pos];
    const cls = left===0?"full":(left>=ROUNDS-picks.length/nTeams?"urgent":"");
    return `<div class="need-row ${cls}">
      <span class="p">${pos}</span>
      <span class="c">${counts[pos]}/${LIMITS[pos]}</span>
      <span class="who">${held.join(", ")||"-"}</span></div>`;
  }).join("");

  // Roster pace. With 15 rounds and a fixed 2/5/5/3 shape, a balanced path
  // takes roughly LIMIT * (rounds done / 15) of each position by now. This
  // does not force anything, it just shows where you have drifted, because
  // the model optimises value and can leave you thin somewhere late.
  const myPicks = mine.size;
  document.getElementById("balance").innerHTML = POS.map(pos=>{
    const target = LIMITS[pos] * (myPicks/ROUNDS);
    const have = counts[pos];
    const behind = have < target - 0.75;
    return `<div class="balp ${behind?"behind":""}">
      <div class="bl">${pos}</div>
      <div class="bv">${have} <span style="color:var(--muted);font-weight:400">
        vs ${target.toFixed(1)} on pace</span></div></div>`;
  }).join("");

  // best available by position
  document.getElementById("pos4").innerHTML = POS.map(pos=>{
    const g = av.filter(p=>p.pos===pos).sort((a,b)=>b.vorp-a.vorp).slice(0,7);
    let html=`<div class="pcol"><h4>${pos}
      <span class="n">${av.filter(p=>p.pos===pos).length} left${need[pos]?` &middot; need ${need[pos]}`:" &middot; full"}</span></h4>`;
    let lastTier=null;
    for(const p of g){
      if(lastTier!==null && p.tier!==lastTier)
        html+=`<div class="tierbreak" data-l="tier ${p.tier}"></div>`;
      lastTier=p.tier;
      const s=surv[p.i]||0;
      const sc=s<0.3?"risk-hi":s>0.75?"risk-lo":"risk-mid";
      html+=`<div class="pr ${need[pos]?"":"dim"}" data-i="${p.i}">
        <div><div class="n1">${p.n}${slHtml(p)}</div>
             <div class="n2">${p.t} &middot; ${startHtml(p)}${fdrHtml(p)}${flags(p)}</div></div>
        <div><div class="v">${p.vorp>0?"+":""}${p.vorp.toFixed(0)}</div>
             <div class="s ${sc}">${(s*100).toFixed(0)}%</div></div></div>`;
    }
    return html+"</div>";
  }).join("");

  // sleeper watch
  const slAvail = av.filter(p=>p.sl)
    .sort((a,b)=> (b.sl.tier===0?-1:b.sl.tier) - (a.sl.tier===0?-1:a.sl.tier)
                  || b.vorp - a.vorp);
  const slPanel = document.getElementById("slPanel");
  if(!slAvail.length){
    slPanel.classList.add("hide");
  } else {
    slPanel.classList.remove("hide");
    document.getElementById("slRows").innerHTML = slAvail.map(p=>{
      const s = surv[p.i]||0;
      const sc = s<0.3?"risk-hi":s>0.75?"risk-lo":"risk-mid";
      return `<div class="slcard ${p.sl.tier===0?"avoid":""}" data-i="${p.i}">
        <div class="sh">
          <span class="sn">${p.n} ${slHtml(p)}</span>
          <span class="sv">${p.pos} &middot; ${p.vorp>0?"+":""}${p.vorp.toFixed(0)}</span>
        </div>
        <div class="sd">${p.sl.note}</div>
        <div class="sm">${p.t} &middot; ${startHtml(p)} &middot;
          <span class="${sc}">${(s*100).toFixed(0)}% to last</span> ${fdrHtml(p)}</div>
      </div>`;
    }).join("");
  }

  // runs
  const recent = picks.slice(-10);
  document.getElementById("runs").innerHTML = POS.map(pos=>{
    const n = recent.filter(x=>byId[x.i]&&byId[x.i].pos===pos).length;
    const left = av.filter(p=>p.pos===pos&&p.vorp>0).length;
    const hot = n>=4;
    return `<div class="run ${hot?"hot":""}">
      <div class="rp">${pos}</div>
      <div class="rv">${n} <span style="font-size:11px;color:var(--muted)">of last 10</span></div>
      <div class="rb"><div class="rf" style="width:${Math.min(100,n*10)}%"></div></div>
      <div class="rp" style="margin-top:5px;font-weight:400">${left} above replacement</div>
    </div>`;
  }).join("");

  // log
  document.getElementById("logCount").innerHTML =
    `${picks.length} picks &middot; ${mine.size} yours`;
  let html="",lastR=null;
  for(let k=picks.length-1;k>=0;k--){
    const e=picks[k],p=byId[e.i];
    const rd = e.rd || Math.ceil((k+1)/nTeams);
    const pk = e.pk || ((k%nTeams)+1);
    if(rd!==lastR){ html+=`<div class="rsep">Round ${rd}</div>`; lastR=rd; }
    html+=`<div class="lg ${e.mine?"me":""} ${freshIds.has(e.i)?"fresh":""}">
      <span class="rd">${rd}.${pk}</span>
      <span>${p?p.n:"player "+e.i}</span>
      <span class="rd">${p?p.pos:""}</span>
      <span class="rd">${p?p.t:""}</span>
      <span class="tm">${e.mine?"YOU":(e.team||"")}</span></div>`;
  }
  document.getElementById("logRows").innerHTML = html;
  saveState();
}

/* ================= live polling ================= */
function setStatus(kind,txt){
  const el=document.getElementById("status");
  el.className="chip "+kind;
  document.getElementById("statusTxt").textContent=txt;
}

async function pollLeague(){
  try{
    const r = await fetch("/api/league",{cache:"no-store"});
    const d = await r.json();
    if(d.league&&d.league.name) document.getElementById("lgName").textContent=d.league.name;
    const es = d.league_entries||[];
    es.forEach(e=>{ entriesById[e.id]=e.entry_name; entriesById[e.entry_id]=e.entry_name; });
    if(es.length){
      nTeams=es.length; document.getElementById("teams").value=nTeams; fillSlots();
    }
  }catch(e){ /* league details are cosmetic; ignore failures */ }
}

async function pollChoices(){
  try{
    const r = await fetch("/api/choices",{cache:"no-store"});
    if(!r.ok) throw new Error("HTTP "+r.status);
    const d = await r.json();
    applyLive(d);
    setStatus("live", `live \u00b7 ${picks.length} picks`);
  }catch(e){
    setStatus("err","connection lost, retrying");
  }
}

function applyLive(d){
  const known=new Set(PLAYERS.map(p=>p.i));
  const ch=(d.choices||[]).slice()
    .sort((a,b)=>(a.index??(a.round*1000+a.pick))-(b.index??(b.round*1000+b.pick)));
  const next=[];
  for(const c of ch){
    if(!known.has(c.element)) continue;
    next.push({i:c.element, mine:MY_IDS.has(c.entry), rd:c.round, pk:c.pick,
               team:c.entry_name||entriesById[c.entry]||""});
  }
  // element_status is the current owner, so it catches waivers and trades.
  const seen=new Set(next.map(x=>x.i));
  for(const s of (d.element_status||[])){
    if(s.owner==null||seen.has(s.element)||!known.has(s.element)) continue;
    next.push({i:s.element, mine:MY_IDS.has(s.owner),
               team:entriesById[s.owner]||""});
  }

  // Work out who sits where. A snake reverses on even rounds, so a pick's
  // seat is recoverable from any round, not just the first. That means the
  // order (and your slot) is pinned down within the first few picks rather
  // than after a full round.
  const seats = order.slice();
  for(const c of ch){
    if(c.round==null||c.pick==null) continue;
    const seat = (c.round%2===1) ? c.pick-1 : nTeams-c.pick;
    if(seat>=0 && seat<nTeams) seats[seat] = c.entry;
  }
  order = seats;
  const mineSeat = order.findIndex(e=>e!=null && MY_IDS.has(e));
  if(mineSeat>=0){
    slot = mineSeat+1; slotLocked = true;
    document.getElementById("slot").value = slot;
  }

  if(next.length!==lastCount){
    freshIds = new Set(next.slice(lastCount<0?next.length:lastCount).map(x=>x.i));
    lastCount = next.length;
    picks = next; rebuild(); render();
    setTimeout(()=>{ freshIds.clear(); }, 2000);
  }
}

/* ================= manual mode ================= */
function mark(id,isMine){
  const at=picks.findIndex(p=>p.i===id);
  if(at>=0) picks.splice(at,1);
  picks.push({i:id,mine:isMine});
  rebuild(); render();
}
document.addEventListener("click",e=>{
  const el=e.target.closest("[data-i]");
  if(!el) return;
  const id=parseInt(el.dataset.i);
  if(LIVE) return;                    // live mode is driven by the API
  mark(id,true);                      // clicking a name drafts him to you
});
const q=document.getElementById("q");
if(q){
  q.addEventListener("keydown",e=>{
    if(e.key!=="Enter") return;
    const t=q.value.trim().toLowerCase();
    if(!t) return;
    const hit=available().filter(p=>p.s.includes(t))
      .sort((a,b)=>b.vorp-a.vorp)[0];
    if(hit){ mark(hit.i,e.shiftKey); q.value=""; }
  });
}
document.getElementById("undo").addEventListener("click",()=>{
  if(!picks.length) return; picks.pop(); rebuild(); render();
});
document.getElementById("reset").addEventListener("click",()=>{
  if(LIVE){ alert("Live mode follows your league. Nothing to reset."); return; }
  if(!confirm("Clear every pick?")) return;
  picks=[]; rebuild(); render();
});

const teamsSel=document.getElementById("teams");
teamsSel.innerHTML=[4,6,8,10,12,14,16].map(n=>`<option value="${n}">${n} managers</option>`).join("");
const slotSel=document.getElementById("slot");
function fillSlots(){
  slotSel.innerHTML=Array.from({length:nTeams},(_,i)=>
    `<option value="${i+1}">pick ${i+1} of ${nTeams}</option>`).join("");
  if(slot>nTeams) slot=nTeams;
  slotSel.value=slot;
}
teamsSel.addEventListener("change",()=>{nTeams=parseInt(teamsSel.value);fillSlots();render();});
slotSel.addEventListener("change",()=>{slot=parseInt(slotSel.value);slotLocked=false;render();});

/* ================= boot ================= */
if(!LIVE){
  document.getElementById("manual").classList.remove("hide");
  document.getElementById("undo").classList.remove("hide");
  loadState();
}
teamsSel.value=nTeams; fillSlots(); render();

if(LIVE){
  setStatus("live","connecting");
  pollLeague().then(()=>{ pollChoices(); render(); });
  setInterval(pollChoices, 4000);
  setInterval(pollLeague, 60000);
}
</script>
</body>
</html>
"""


def build(players: list[Player], n_teams: int, slot: int = 1,
          live: bool = False, my_ids: set[int] | None = None,
          sample: bool = False) -> str:
    rows = []
    for p in players:
        rows.append({
            "i": p.draft_id, "n": p.name, "pos": p.pos, "t": p.team_short,
            "tm": p.team, "proj": round(p.proj), "adp": p.draft_rank or 9999,
            "f": p.flags[:4], "news": p.news[:140],
            "fdr": p.fdr, "st": p.start_pct,
            "sl": p.sleeper,
            "s": f"{p.name} {p.full_name}".lower(),
        })
    rows.sort(key=lambda r: r["proj"], reverse=True)
    rows = rows[:400]

    banner = ""
    if sample:
        banner = ('<div class="warnbar"><b>Sample data.</b> These are not real '
                  'players. Run <code>py draft.py --deep fetch</code> and start '
                  'again to build this from the live FPL list.</div>')
    elif not live:
        banner = ('<div class="warnbar"><b>Manual mode.</b> This file is not '
                  'connected to your league. For live tracking run '
                  '<code>py draft.py serve --league &lt;id&gt; --entry &lt;id&gt;</code>'
                  '.</div>')

    from strategy import LOOKAHEAD
    return (TEMPLATE
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False))
            .replace("__STARTERS__", json.dumps(TYPICAL_STARTERS))
            .replace("__LIMITS__", json.dumps(SQUAD_LIMITS))
            .replace("__LOOKAHEAD__", str(LOOKAHEAD))
            .replace("__NTEAMS__", str(n_teams))
            .replace("__SLOT__", str(slot))
            .replace("__LIVE__", "true" if live else "false")
            .replace("__MY_IDS__", json.dumps(sorted(my_ids or [])))
            .replace("__BANNER__", banner))
