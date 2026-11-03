#!/usr/bin/env python3
"""Live team board in the browser: kanban, epic → story → task tree, search, agent status, team chat.

  python .sdlc/bin/board_server.py [--port 8765] [--host 127.0.0.1] [--db PATH]

Reads the same board the agents write (board.py). The page polls every 1.5 s, so moves, QA verdicts,
merges and agent activity show up live. You can message any agent (or the whole team) from the page;
agents read it with `board.py inbox`. Binds to localhost by default — the page has no login.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from board import Board  # noqa: E402

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Team Board</title>
<style>
:root{
  --bg:#0d0f13;--panel:#151820;--panel2:#1b1f29;--line:#272c38;--text:#e8eaef;--muted:#9aa1ae;--faint:#6c7381;
  --blue:#7cc4ff;--green:#a6e35a;--amber:#ffc65c;--red:#ff7a7a;--violet:#b9a4ff;--teal:#5ee0c8;
  --shadow:0 8px 28px rgba(0,0,0,.35);
}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){
  --bg:#f5f6f8;--panel:#ffffff;--panel2:#f0f2f5;--line:#dfe3ea;--text:#16181d;--muted:#596070;--faint:#7a8191;
  --blue:#0b6bcb;--green:#2f7d1a;--amber:#9a6200;--red:#c42b2b;--violet:#5b45c7;--teal:#0e7d6c;--shadow:0 6px 20px rgba(20,30,50,.10);}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
button,input,select,textarea{font:inherit;color:inherit}
a{color:var(--blue)}
.mono{font-family:ui-monospace,"JetBrains Mono",Menlo,Consolas,monospace}
header{display:flex;flex-wrap:wrap;align-items:center;gap:14px 20px;padding:16px 22px;border-bottom:1px solid var(--line);background:var(--panel)}
.brand{display:flex;align-items:center;gap:10px}
.logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--blue),var(--violet));display:grid;place-items:center;color:#0d0f13;font-weight:800}
h1{margin:0;font-size:17px;font-weight:700;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:12.5px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;border:1px solid var(--line);font-size:12px;color:var(--muted);background:var(--panel2);white-space:nowrap}
.pill b{color:var(--text);font-weight:600}
.dot{width:8px;height:8px;border-radius:50%;background:var(--faint)}
.dot.running,.dot.working{background:var(--green);box-shadow:0 0 0 3px color-mix(in srgb,var(--green) 25%,transparent);animation:pulse 1.4s infinite}
.dot.helping{background:var(--violet);animation:pulse 1.4s infinite}
.dot.done{background:var(--blue)} .dot.needs-human{background:var(--red)}
@keyframes pulse{50%{opacity:.45}}
.grow{flex:1}
.progress{min-width:180px}
.bar{height:8px;border-radius:99px;background:var(--panel2);border:1px solid var(--line);overflow:hidden}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--teal),var(--green));transition:width .5s}
.search{display:flex;align-items:center;gap:8px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:0 10px;min-width:240px;height:38px}
.search input{border:0;background:transparent;outline:none;width:100%}
.team{display:flex;gap:10px;overflow-x:auto;padding:14px 22px;border-bottom:1px solid var(--line)}
.agent{min-width:230px;max-width:280px;flex:1;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:11px 12px;display:flex;gap:10px;align-items:flex-start}
.av{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-weight:800;font-size:12px;color:#0d0f13;flex:none}
.av.developer{background:var(--blue)} .av.qa{background:var(--green)} .av.planner,.av.helper{background:var(--violet)} .av.human,.av.lead{background:var(--amber)} .av.designer{background:#ff8fc8}
.dot.designing{background:#ff8fc8;animation:pulse 1.4s infinite}
.banner{margin:14px 22px 0;padding:14px 16px;border-radius:14px;border:1px solid color-mix(in srgb,#ff8fc8 45%,var(--line));background:color-mix(in srgb,#ff8fc8 10%,var(--panel));display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.banner b{font-size:14.5px} .banner .grow{min-width:120px}
.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--line)} .btn.ok{background:var(--green)} .btn.warn{background:var(--amber)}
.card.design{border-style:dashed;border-color:color-mix(in srgb,#ff8fc8 55%,var(--line))}
.s-review{color:#ff8fc8}
textarea.fb{width:100%;min-height:90px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px;margin:8px 0}
.agent .nm{display:flex;align-items:center;gap:7px;font-weight:650}
.agent .act{color:var(--muted);font-size:12px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
.agent .meta{color:var(--faint);font-size:11.5px;margin-top:2px}
main{display:flex;gap:16px;padding:16px 22px;align-items:flex-start}
.left{flex:1;min-width:0}
.right{width:360px;flex:none;position:sticky;top:12px}
.tabs{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
.tab{border:1px solid var(--line);background:var(--panel);padding:7px 14px;border-radius:10px;cursor:pointer;color:var(--muted)}
.tab[aria-selected="true"]{color:var(--text);background:var(--panel2);border-color:color-mix(in srgb,var(--blue) 50%,var(--line))}
select{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:7px 10px}
.kanban{display:grid;grid-template-columns:repeat(5,minmax(168px,1fr));gap:12px;overflow-x:auto;padding-bottom:6px}
.col{background:var(--panel);border:1px solid var(--line);border-radius:14px;min-height:300px;display:flex;flex-direction:column}
.colh{display:flex;align-items:center;justify-content:space-between;padding:11px 12px;border-bottom:1px solid var(--line);font-weight:650;font-size:13px}
.colh .n{color:var(--muted);font-weight:600;background:var(--panel2);border-radius:99px;padding:1px 9px;font-size:12px}
.colh .sw{width:9px;height:9px;border-radius:3px;display:inline-block;margin-right:7px}
.cards{padding:10px;display:flex;flex-direction:column;gap:9px}
.card{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:10px 11px;cursor:pointer;transition:transform .15s,border-color .15s;position:relative}
.card:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--blue) 45%,var(--line))}
.card.live{border-color:color-mix(in srgb,var(--green) 60%,var(--line));box-shadow:0 0 0 1px color-mix(in srgb,var(--green) 30%,transparent)}
.card .top{display:flex;justify-content:space-between;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.card .ttl{margin:6px 0 8px;font-weight:600;line-height:1.35}
.card .foot{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.tag{font-size:11px;padding:2px 7px;border-radius:6px;background:color-mix(in srgb,var(--sc) 16%,transparent);color:var(--sc);border:1px solid color-mix(in srgb,var(--sc) 35%,transparent);white-space:nowrap;max-width:150px;overflow:hidden;text-overflow:ellipsis}
.chip{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:1px 6px}
.chip.red{color:var(--red);border-color:color-mix(in srgb,var(--red) 40%,var(--line))}
.chip.amber{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 40%,var(--line))}
.mini{width:22px;height:22px;border-radius:7px;font-size:10px}
.livebar{font-size:11.5px;color:var(--green);margin-top:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.empty{color:var(--faint);font-size:12.5px;text-align:center;padding:18px 6px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.panel h3{margin:0;padding:11px 14px;border-bottom:1px solid var(--line);font-size:13px;display:flex;justify-content:space-between;align-items:center}
.feed{max-height:calc(100vh - 330px);min-height:260px;overflow-y:auto;padding:6px 0}
.ev{display:flex;gap:9px;padding:7px 14px;font-size:12.5px}
.ev .av{width:24px;height:24px;border-radius:7px;font-size:9.5px}
.ev .who{font-weight:650} .ev .when{color:var(--faint);font-size:11px;margin-left:4px}
.ev .txt{color:var(--muted);word-break:break-word}
.ev.msg .txt{color:var(--text);background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:6px 9px;margin-top:3px}
.ev.qa-pass .txt{color:var(--green)} .ev.qa-fail .txt{color:var(--red)} .ev.merge .txt{color:var(--teal)}
.compose{display:flex;gap:6px;padding:10px;border-top:1px solid var(--line)}
.compose input{flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:8px 10px;min-width:0}
.compose button,.btn{background:var(--blue);color:#0d0f13;border:0;border-radius:9px;padding:8px 13px;font-weight:700;cursor:pointer}
.tree .ep{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden}
.tree .eh{padding:13px 15px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--line)}
.tree .st{padding:10px 15px;border-bottom:1px solid var(--line)}
.tree .sh{display:flex;align-items:center;gap:10px;font-weight:600}
.tree .tk{display:grid;grid-template-columns:62px 1fr 92px 70px;gap:10px;align-items:center;padding:7px 0 7px 18px;border-left:2px solid var(--line);margin-left:6px;cursor:pointer;font-size:13px}
.tree .tk:hover{background:var(--panel2)}
.st-badge{font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);white-space:nowrap;text-align:center}
.s-todo{color:var(--muted)} .s-in_progress{color:var(--blue)} .s-blocked{color:var(--red)} .s-in_qa{color:var(--amber)} .s-done{color:var(--green)}
.mbar{width:120px} .mbar .bar{height:6px}
dialog{border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:16px;padding:0;width:min(760px,94vw);max-height:88vh;box-shadow:var(--shadow)}
dialog::backdrop{background:rgba(5,7,10,.6)}
.dh{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.db{padding:14px 18px;overflow-y:auto;max-height:calc(88vh - 80px)}
.kv{display:grid;grid-template-columns:120px 1fr;gap:6px 12px;font-size:13px;margin-bottom:14px}
.kv dt{color:var(--muted)} .kv dd{margin:0}
.sec{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);margin:16px 0 6px}
ul.ac{margin:0;padding-left:18px} pre.desc{white-space:pre-wrap;margin:0;font:inherit;color:var(--muted)}
.x{background:transparent;border:1px solid var(--line);border-radius:9px;width:34px;height:34px;cursor:pointer;color:var(--muted)}
@media (max-width:1100px){main{flex-direction:column}.right{width:100%;position:static}.kanban{grid-template-columns:repeat(5,minmax(220px,1fr))}}
@media (max-width:640px){header,.team,main{padding-left:16px;padding-right:16px}.search{min-width:0;width:100%}.tree .tk{grid-template-columns:52px 1fr 74px}.tree .tk .hide-s{display:none}}
</style>
</head>
<body>
<header>
  <div class="brand"><div class="logo">✓</div><div><h1 id="title">Team Board</h1><div class="sub" id="subtitle">loading…</div></div></div>
  <span class="pill" id="runpill"><span class="dot" id="rundot"></span><b id="runstate">—</b></span>
  <span class="pill" id="trackerpill">tracker <b id="tracker">internal</b></span>
  <span class="pill">branch <b class="mono" id="branch">—</b></span>
  <div class="grow"></div>
  <div class="progress"><div class="sub" style="display:flex;justify-content:space-between"><span>Progress</span><span id="progtxt">0/0</span></div><div class="bar"><i id="progbar" style="width:0"></i></div></div>
  <label class="search"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="q" placeholder="Search epics, stories, tasks, agents…" aria-label="Search"></label>
</header>
<div id="banner"></div>
<section class="team" id="team" aria-label="Agent team"></section>
<main>
  <div class="left">
    <div class="tabs" role="tablist">
      <button class="tab" role="tab" data-view="kanban" aria-selected="true">Kanban</button>
      <button class="tab" role="tab" data-view="tree" aria-selected="false">Epics &amp; stories</button>
      <span class="grow"></span>
      <select id="fstory" aria-label="Filter by story"><option value="">All stories</option></select>
      <select id="fwho" aria-label="Filter by agent"><option value="">Everyone</option></select>
    </div>
    <div id="kanban" class="kanban"></div>
    <div id="tree" class="tree" hidden></div>
  </div>
  <aside class="right">
    <div class="panel">
      <h3><span>Team chat &amp; activity</span><label class="sub"><input type="checkbox" id="onlymsg"> messages only</label></h3>
      <div class="feed" id="feed" aria-live="polite"></div>
      <form class="compose" id="compose">
        <select id="to" aria-label="Recipient"><option value="all">@all</option></select>
        <input id="msg" placeholder="Message the team…" autocomplete="off" aria-label="Message">
        <button type="submit">Send</button>
      </form>
    </div>
  </aside>
</main>
<dialog id="dlg"><div class="dh"><div><div class="sub mono" id="dkey"></div><h2 id="dtitle" style="margin:4px 0 0;font-size:18px"></h2></div><button class="x" id="dclose" aria-label="Close">✕</button></div><div class="db" id="dbody"></div></dialog>
<script>
const COLS=[["todo","To Do","var(--muted)"],["in_progress","In Progress","var(--blue)"],["blocked","Blocked","var(--red)"],["in_qa","Review & QA","var(--amber)"],["done","Done","var(--green)"]];
const LABEL=Object.assign(Object.fromEntries(COLS.map(c=>[c[0],c[1]])),{in_qa:"In QA",review:"Needs your approval"});
const COLOF=st=>st==="review"?"in_qa":st;
const STORY_COLORS=["var(--violet)","var(--teal)","var(--amber)","var(--blue)","var(--red)","var(--green)"];
let S={items:[],agents:[],events:[],messages:[],meta:{}},since=0,view="kanban",openKey=null;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ini=n=>{n=n||"?";const m=n.match(/^([a-z])[a-z]*-(\d+)$/i);return m?(m[1]+m[2]).toUpperCase():n.replace(/[^a-z0-9]/gi,"").slice(0,2).toUpperCase()||"?"};
const roleOf=n=>{const a=S.agents.find(x=>x.name===n);return a?a.role:(n==="human"?"human":n==="lead"||n==="sync"?"lead":"developer")};
const ago=ts=>{if(!ts)return"";const s=Math.max(0,(Date.now()-Date.parse(ts))/1000);return s<60?Math.floor(s)+"s":s<3600?Math.floor(s/60)+"m":Math.floor(s/3600)+"h"};
function storyColor(k){const st=S.items.filter(i=>i.type==="story");const i=st.findIndex(s=>s.key===k);return STORY_COLORS[(i<0?0:i)%STORY_COLORS.length]}
function match(t,q){if(!q)return true;const story=S.items.find(i=>i.key===t.parent_key)||{};return [t.key,t.title,t.description,t.assignee,LABEL[t.status],story.title,story.key,(t.files||[]).join(" ")].join(" ").toLowerCase().includes(q)}
function filtered(){const q=$("q").value.trim().toLowerCase(),fs=$("fstory").value,fw=$("fwho").value;
  return S.items.filter(i=>(i.type==="task"||i.type==="design")&&match(i,q)&&(!fs||i.parent_key===fs||i.type==="design")&&(!fw||i.assignee===fw||(i.qa_by||"").endsWith(fw)))}
function liveOn(key){return S.agents.find(a=>a.item_key===key&&(a.status==="working"||a.status==="helping"||a.status==="designing"))}
function renderBanner(){const d=S.items.find(i=>i.type==="design"&&i.status==="review");
  if(!d){$("banner").innerHTML="";return}
  const last=[...S.events].reverse().find(e=>e.item_key===d.key&&e.actor==="designer"&&e.kind==="status");
  $("banner").innerHTML=`<div class="banner" role="region" aria-label="Design approval"><span style="font-size:22px" aria-hidden="true">🎨</span>
   <div class="grow"><b>Design ${esc(d.key)} is ready for your review</b><div class="sub">${esc(last?last.text.split(": ").slice(1).join(": "):d.title)}</div></div>
   <a class="btn ghost" href="design/${esc(d.key)}" target="_blank" rel="noopener">Open mockup ↗</a>
   <button class="btn ok" data-design="approve" data-dkey="${esc(d.key)}">Approve</button>
   <button class="btn warn" data-design="changes" data-dkey="${esc(d.key)}">Request changes</button></div>`}
async function designAction(key,action){let text="";
  if(action==="changes"){text=prompt("What should the designer change?");if(!text)return}
  const r=await fetch("api/design",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key,action,text})});
  if(!r.ok){alert((await r.json()).error||"failed")}since=Math.max(0,since-1)}
async function resumeTask(key){const text=prompt(`Guidance for the team on ${key}:`);if(!text)return;
  const r=await fetch("api/resume",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key,text})});
  if(!r.ok){alert((await r.json()).error||"failed")}since=Math.max(0,since-1)}
function card(t){
  if(t.type==="design"){const live=liveOn(t.key);const dm=(S.meta.design||{});
    return `<div class="card design${live?" live":""}" data-key="${esc(t.key)}" tabindex="0" role="button" aria-label="${esc(t.key+" "+t.title)}">
     <div class="top"><span class="mono">🎨 ${esc(t.key)}</span><span class="chip">${esc(dm.mode||"design")}</span></div>
     <div class="ttl">${esc(t.title)}</div>
     <div class="foot"><span class="av mini designer" title="designer">DS</span>
      ${t.status==="review"?`<span class="chip" style="color:#ff8fc8">Needs your approval</span>`:""}
      ${t.qa_rounds?`<span class="chip amber">changes ×${t.qa_rounds}</span>`:""}
      ${t.status!=="todo"?`<a href="design/${esc(t.key)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">mockup ↗</a>`:""}</div>
     ${live?`<div class="livebar">● designer: ${esc(live.activity||"designing")}</div>`:""}</div>`}
  const story=S.items.find(i=>i.key===t.parent_key)||{};const live=liveOn(t.key);
  const waiting=(t.depends_on||[]).filter(d=>(S.items.find(i=>i.key===d)||{}).status!=="done");
  const qa=(t.qa_by||"");const qaName=qa.includes(":")?qa.split(":")[1]:qa;
  return `<div class="card${live?" live":""}" data-key="${esc(t.key)}" tabindex="0" role="button" aria-label="${esc(t.key+" "+t.title)}">
   <div class="top"><span class="mono">${esc(t.key)}</span><span>${t.ext_url?`<a href="${esc(t.ext_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(S.meta.tracker||"link")} ↗</a>`:""}</span></div>
   <div class="ttl">${esc(t.title)}</div>
   <div class="foot">
     <span class="tag" style="--sc:${storyColor(t.parent_key)}" title="${esc(story.title)}">${esc(story.key)} · ${esc(story.title||"")}</span>
     ${t.assignee?`<span class="av mini ${roleOf(t.assignee)}" title="developer ${esc(t.assignee)}">${ini(t.assignee)}</span>`:""}
     ${qaName&&t.status!=="todo"?`<span class="av mini qa" title="QA ${esc(qaName)}">${ini(qaName)}</span>`:""}
     ${t.qa_rounds?`<span class="chip red" title="returned by QA">↺ ${t.qa_rounds}</span>`:""}
     ${waiting.length&&t.status==="todo"?`<span class="chip amber" title="waiting on">🔒 ${esc(waiting.join(", "))}</span>`:""}
   </div>
   ${live?`<div class="livebar">● ${esc(live.name)}: ${esc(live.activity||"working")}</div>`:""}
  </div>`}
function renderKanban(){const ts=filtered();$("kanban").innerHTML=COLS.map(([k,l,c])=>{const cs=ts.filter(t=>COLOF(t.status)===k);
  return `<section class="col" aria-label="${l}"><div class="colh"><span><span class="sw" style="background:${c}"></span>${l}</span><span class="n">${cs.length}</span></div><div class="cards">${cs.map(card).join("")||`<div class="empty">—</div>`}</div></section>`}).join("")}
function pct(list){const d=list.filter(t=>t.status==="done").length;return list.length?Math.round(100*d/list.length):0}
function renderTree(){const q=$("q").value.trim().toLowerCase();const out=[];
  for(const e of S.items.filter(i=>i.type==="epic")){const stories=S.items.filter(i=>i.parent_key===e.key);
    const all=S.items.filter(i=>i.type==="task"&&stories.some(s=>s.key===i.parent_key));
    let body="";for(const s of stories){const ts=S.items.filter(i=>i.parent_key===s.key&&match(i,q));
      if(q&&!ts.length&&!s.title.toLowerCase().includes(q))continue;const allS=S.items.filter(i=>i.parent_key===s.key);
      body+=`<div class="st"><div class="sh"><span class="tag" style="--sc:${storyColor(s.key)}">${esc(s.key)}</span><span style="flex:1">${esc(s.title)}</span><span class="st-badge s-${s.status}">${LABEL[s.status]||s.status}</span><span class="mbar"><span class="bar"><i style="width:${pct(allS)}%"></i></span></span>${s.ext_url?`<a href="${esc(s.ext_url)}" target="_blank" rel="noopener">↗</a>`:""}</div>
      ${ts.map(t=>`<div class="tk" data-key="${esc(t.key)}" tabindex="0" role="button"><span class="mono sub">${esc(t.key)}</span><span>${esc(t.title)}</span><span class="st-badge s-${t.status}">${LABEL[t.status]}</span><span class="sub hide-s">${esc(t.assignee||"")}</span></div>`).join("")}</div>`}
    const ds=S.items.filter(i=>i.type==="design"&&i.parent_key===e.key);
    body=ds.map(d=>`<div class="st"><div class="sh" data-key="${esc(d.key)}" style="cursor:pointer"><span class="tag" style="--sc:#ff8fc8">🎨 ${esc(d.key)}</span><span style="flex:1">${esc(d.title)}</span><span class="st-badge s-${d.status}">${LABEL[d.status]||d.status}</span></div></div>`).join("")+body;
    out.push(`<div class="ep"><div class="eh"><span class="logo" style="width:26px;height:26px;font-size:12px">E</span><div style="flex:1"><div style="font-weight:700">${esc(e.title)}</div><div class="sub">${esc(e.key)} · ${stories.length} stories · ${all.length} tasks${e.ext_url?` · <a href="${esc(e.ext_url)}" target="_blank" rel="noopener">${esc(S.meta.tracker)} ↗</a>`:""}</div></div><span class="st-badge s-${e.status}">${LABEL[e.status]||e.status}</span><span class="mbar"><span class="bar"><i style="width:${pct(all)}%"></i></span></span></div>${body}</div>`)}
  $("tree").innerHTML=out.join("")||`<div class="empty">No epics yet — run team.py plan</div>`}
function renderTeam(){const ag=S.agents.filter(a=>a.role!=="planner"||a.status==="working");
  $("team").innerHTML=ag.map(a=>{const t=S.items.find(i=>i.key===a.item_key);return `<div class="agent"><div class="av ${esc(a.role)}">${ini(a.name)}</div><div style="min-width:0">
   <div class="nm">${esc(a.name)} <span class="dot ${esc(a.status)}" title="${esc(a.status)}"></span><span class="sub">${esc(a.role)}</span></div>
   <div class="act" title="${esc(a.activity)}">${t?`<b class="mono">${esc(t.key)}</b> `:""}${esc(a.activity||a.status)}</div>
   <div class="meta">${a.runs||0} runs · $${(a.cost||0).toFixed(2)}${a.worktree?` · <span class="mono">${esc(a.worktree)}</span>`:""}</div></div></div>`}).join("")||`<div class="sub">No agents yet</div>`;
  const opts=["all","developer","qa",...S.agents.map(a=>a.name)];const cur=$("to").value;$("to").innerHTML=opts.map(o=>`<option value="${esc(o)}">@${esc(o)}</option>`).join("");$("to").value=opts.includes(cur)?cur:"all";
  const fw=$("fwho").value;$("fwho").innerHTML=`<option value="">Everyone</option>`+S.agents.filter(a=>a.role!=="planner").map(a=>`<option>${esc(a.name)}</option>`).join("");$("fwho").value=fw;
  const fs=$("fstory").value;$("fstory").innerHTML=`<option value="">All stories</option>`+S.items.filter(i=>i.type==="story").map(s=>`<option value="${esc(s.key)}">${esc(s.key+" · "+s.title)}</option>`).join("");$("fstory").value=fs}
function evClass(e){if(e.kind==="message")return"msg";if(e.kind==="qa")return e.text.startsWith("PASS")?"qa-pass":"qa-fail";if(e.kind==="merge")return"merge";return""}
function renderFeed(){const only=$("onlymsg").checked;const q=$("q").value.trim().toLowerCase();
  const evs=S.events.filter(e=>(!only||e.kind==="message"||e.kind==="qa"||e.kind==="help")&&(!q||(e.text+" "+e.actor+" "+(e.item_key||"")).toLowerCase().includes(q))).slice(-160);
  const f=$("feed");const atBottom=f.scrollHeight-f.scrollTop-f.clientHeight<40;
  f.innerHTML=evs.map(e=>`<div class="ev ${evClass(e)}"><div class="av ${esc(roleOf(e.actor))}">${ini(e.actor)}</div><div style="min-width:0"><div><span class="who">${esc(e.actor)}</span>${e.item_key?` <a href="#" data-key="${esc(e.item_key)}" class="mono">${esc(e.item_key)}</a>`:""}<span class="when">${ago(e.ts)}</span></div><div class="txt">${esc(e.text)}</div></div></div>`).join("")||`<div class="empty">Quiet so far</div>`;
  if(atBottom)f.scrollTop=f.scrollHeight}
function renderHeader(){const m=S.meta,ts=S.items.filter(i=>i.type==="task"),d=ts.filter(t=>t.status==="done").length;
  $("title").textContent=m.project?`${m.project} · team board`:"Team Board";$("subtitle").textContent=m.change||"no change loaded";
  $("runstate").textContent=m.status||"idle";$("rundot").className="dot "+(m.status||"");$("tracker").textContent=m.tracker||"internal";
  $("branch").textContent=m.integration_branch||"—";$("progtxt").textContent=`${d}/${ts.length} tasks`;$("progbar").style.width=(ts.length?100*d/ts.length:0)+"%";
  const cost=S.agents.reduce((s,a)=>s+(a.cost||0),0);$("subtitle").textContent=(m.change||"")+(cost?` · $${cost.toFixed(2)} est.`:"")}
function detail(key){const t=S.items.find(i=>i.key===key);if(!t)return;openKey=key;
  const story=S.items.find(i=>i.key===t.parent_key)||{};const kids=S.items.filter(i=>i.parent_key===key);
  const evs=S.events.filter(e=>e.item_key===key);
  $("dkey").textContent=`${t.type.toUpperCase()} ${t.key}`;$("dtitle").textContent=t.title;
  $("dbody").innerHTML=`<dl class="kv"><dt>Status</dt><dd><span class="st-badge s-${t.status}">${LABEL[t.status]||t.status}</span>${t.qa_rounds?` <span class="chip red">↺ QA ${t.qa_rounds}</span>`:""}</dd>
   ${t.parent_key?`<dt>Parent</dt><dd><a href="#" data-key="${esc(story.key)}">${esc(story.key)}</a> ${esc(story.title)}</dd>`:""}
   ${t.assignee?`<dt>Developer</dt><dd>${esc(t.assignee)}</dd>`:""}${t.qa_by?`<dt>QA</dt><dd>${esc(t.qa_by)}</dd>`:""}
   ${t.branch?`<dt>Branch</dt><dd class="mono">${esc(t.branch)}</dd>`:""}${(t.depends_on||[]).length?`<dt>Depends on</dt><dd>${t.depends_on.map(d=>`<a href="#" data-key="${esc(d)}">${esc(d)}</a>`).join(", ")}</dd>`:""}
   ${(t.files||[]).length?`<dt>Files</dt><dd class="mono" style="font-size:12px">${t.files.map(esc).join("<br>")}</dd>`:""}
   ${t.ext_url?`<dt>${esc(S.meta.tracker)}</dt><dd><a href="${esc(t.ext_url)}" target="_blank" rel="noopener">${esc(t.ext_key)} ↗</a></dd>`:""}
   ${t.type==="design"&&t.status!=="todo"?`<dt>Mockup</dt><dd><a href="design/${esc(t.key)}" target="_blank" rel="noopener">open mockup ↗</a> · <a href="design/${esc(t.key)}/notes" target="_blank" rel="noopener">design notes</a></dd>`:""}
   ${t.type==="design"&&t.status==="review"?`<dt>Decision</dt><dd><button class="btn ok" data-design="approve" data-dkey="${esc(t.key)}">Approve</button> <button class="btn warn" data-design="changes" data-dkey="${esc(t.key)}">Request changes</button></dd>`:""}
   ${(S.meta.escalated||[]).includes(t.key)?`<dt>Escalated</dt><dd><button class="btn warn" data-resume="${esc(t.key)}">Resume with guidance</button></dd>`:""}</dl>
   ${t.description?`<div class="sec">Description</div><pre class="desc">${esc(t.description)}</pre>`:""}
   ${(t.acceptance||[]).length?`<div class="sec">Acceptance criteria</div><ul class="ac">${t.acceptance.map(a=>`<li>${esc(a)}</li>`).join("")}</ul>`:""}
   ${kids.length?`<div class="sec">${t.type==="epic"?"Stories":"Tasks"}</div>${kids.map(k=>`<div class="tk" data-key="${esc(k.key)}" style="display:flex;gap:10px;padding:5px 0;cursor:pointer"><span class="mono sub">${esc(k.key)}</span><span style="flex:1">${esc(k.title)}</span><span class="st-badge s-${k.status}">${LABEL[k.status]||k.status}</span></div>`).join("")}`:""}
   <div class="sec">History</div>${evs.map(e=>`<div class="ev ${evClass(e)}" style="padding:5px 0"><div class="av ${esc(roleOf(e.actor))}">${ini(e.actor)}</div><div><span class="who">${esc(e.actor)}</span><span class="when">${esc((e.ts||"").slice(11,19))}</span><div class="txt">${esc(e.text)}</div></div></div>`).join("")||`<div class="sub">No history yet</div>`}`;
  if(!$("dlg").open)$("dlg").showModal()}
function render(){renderHeader();renderBanner();renderTeam();view==="kanban"?renderKanban():renderTree();renderFeed();if($("dlg").open&&openKey)detail(openKey)}
async function poll(){try{const r=await fetch("api/board?since="+since);const d=await r.json();
  S.items=d.items;S.agents=d.agents;S.meta=d.meta;S.messages=d.messages;
  if(d.events.length){S.events=since?S.events.concat(d.events).slice(-800):d.events;since=d.events[d.events.length-1].id}
  render()}catch(e){$("runstate").textContent="offline"}finally{setTimeout(poll,1500)}}
document.addEventListener("click",e=>{const da=e.target.closest("[data-design]");if(da){designAction(da.dataset.dkey,da.dataset.design);return}
  const rs=e.target.closest("[data-resume]");if(rs){resumeTask(rs.dataset.resume);return}
  const k=e.target.closest("[data-key]");if(k&&!e.target.closest("a[target]")){e.preventDefault();detail(k.dataset.key)}
  const tab=e.target.closest(".tab");if(tab){view=tab.dataset.view;document.querySelectorAll(".tab").forEach(t=>t.setAttribute("aria-selected",t===tab));$("kanban").hidden=view!=="kanban";$("tree").hidden=view!=="tree";render()}});
document.addEventListener("keydown",e=>{if(e.key==="Enter"){const k=e.target.closest&&e.target.closest("[data-key][role=button]");if(k)detail(k.dataset.key)}});
$("dclose").onclick=()=>{openKey=null;$("dlg").close()};$("dlg").addEventListener("close",()=>openKey=null);
["q","fstory","fwho","onlymsg"].forEach(id=>$(id).addEventListener("input",render));
$("compose").onsubmit=async e=>{e.preventDefault();const text=$("msg").value.trim();if(!text)return;$("msg").value="";
  await fetch("api/message",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({to:$("to").value,text,task:openKey})});since=Math.max(0,since-1)};
poll();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    board: Board = None  # set in main
    root: Path = None
    cfg: dict = {}

    def design_file(self, name: str) -> Path | None:
        """The design file from the designer's worktree (latest) or the integration branch (approved)."""
        m = self.board.meta()
        change = m.get("change")
        if not change or not self.root:
            return None
        rel = Path(self.cfg.get("changes_dir", "sdlc/changes")) / change / "design" / name
        wt = self.root / (self.cfg.get("team", {}).get("worktree_dir") or ".sdlc/worktrees")
        for base in (wt / "designer", wt / "integration", self.root):
            p = (base / rel).resolve()
            if p.is_file() and str(p).startswith(str(self.root.resolve())):
                return p
        return None

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path.startswith("/design/"):
            parts = u.path.strip("/").split("/")
            name = "design-notes.md" if len(parts) > 2 and parts[2] == "notes" else "mockup.html"
            p = self.design_file(name)
            if not p:
                return self._json({"error": "no design yet"}, 404)
            body = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if name.endswith(".html") else "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/board":
            since = int((parse_qs(u.query).get("since") or ["0"])[0] or 0)
            self._json(self.board.snapshot(since=since))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/design":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                d = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            it = self.board.item(str(d.get("key") or ""))
            if not it or it["type"] != "design" or it["status"] != "review":
                return self._json({"error": "that design is not waiting for approval"}, 409)
            if d.get("action") == "approve":
                self.board.approve_design(it["key"], str(d.get("text") or "")[:1000])
            elif d.get("action") == "changes" and str(d.get("text") or "").strip():
                self.board.request_design_changes(it["key"], str(d["text"]).strip()[:2000])
            else:
                return self._json({"error": "action must be approve, or changes with text"}, 400)
            return self._json({"ok": True})
        if path == "/api/resume":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                d = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            key, text = str(d.get("key") or ""), str(d.get("text") or "").strip()[:2000]
            if key not in self.board.meta().get("escalated", []):
                return self._json({"error": "that task is not escalated"}, 409)
            if not text:
                return self._json({"error": "give the team some guidance"}, 400)
            self.board.resume(key, text)
            return self._json({"ok": True})
        if path != "/api/message":
            return self._json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            d = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        text = str(d.get("text") or "").strip()[:2000]
        if not text:
            return self._json({"error": "empty"}, 400)
        mid = self.board.send("human", str(d.get("to") or "all")[:40], text, d.get("task") or None)
        self._json({"id": mid})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int)
    ap.add_argument("--db")
    a = ap.parse_args()
    port = a.port
    if not port:
        try:
            from sdlc_core import find_root, load_config
            root = find_root()
            port = load_config(root)["team"]["board_port"] if root else 8765
        except Exception:
            port = 8765
    Handler.board = Board(Path(a.db) if a.db else None)
    try:
        from sdlc_core import find_root, load_config
        Handler.root = find_root() or Handler.board.path.parent.parent.parent
        Handler.cfg = load_config(Handler.root) if (Handler.root / ".sdlc" / "config.json").is_file() else {}
    except Exception:
        Handler.root = Handler.board.path.parent.parent.parent
    srv = ThreadingHTTPServer((a.host, port), Handler)
    print(f"team board: http://{a.host}:{port}   (db {Handler.board.path})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
