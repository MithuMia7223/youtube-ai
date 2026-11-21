#!/usr/bin/env python3
"""
🌐 Video Vault — ১০৮০ ভিডিও ডাউনলোডার (স্থানীয় ওয়েবসাইট)
============================================================

কেন: টেলিগ্রাম বটের ৫০ MB সীমা আর রিকম্প্রেশনের ঝামেলা নেই — এখান থেকে
**অরিজিনাল ফাইল** (১০৮০, কম্প্রেশন ছাড়া) সরাসরি ডাউনলোড হয়।

চালাও:
    ./.venv/bin/python web/app.py            # http://127.0.0.1:8770
    ./.venv/bin/python web/app.py --open     # ব্রাউজারও খুলে দেবে

ফোন থেকে (একই Wi-Fi):
    http://<ম্যাকের-আইপি>:8770

ফিচার:
  • সব ভিডিও এক জায়গায় — সাইজ, রেজোলিউশন, দৈর্ঘ্য, তারিখ
  • প্রতি ভিডিওর থাম্বনেইল (ffmpeg দিয়ে, একবার বানিয়ে ক্যাশ)
  • এক ক্লিকে ডাউনলোড (Content-Disposition: attachment)
  • ১০৮০ না হলে লাল ব্যাজে সতর্কতা
  • কোনো এক্সটার্নাল প্যাকেজ নেই — শুধু Python stdlib + ffmpeg
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIRS = [ROOT / "deliver", ROOT / "videos", ROOT]   # যেখানে ভিডিও খুঁজব
THUMB_DIR = ROOT / "web" / ".thumbs"
PORT = 8770

_FF = shutil.which("ffmpeg") or "ffmpeg"
_PROBE_CACHE: dict[str, tuple[float, dict]] = {}


# ── ffmpeg/ffprobe হেল্পার ──────────────────────────────────────────────────
def probe(path: Path) -> dict:
    """রেজোলিউশন/দৈর্ঘ্য/কোডেক — ৬০ সেকেন্ড ক্যাশ।"""
    now = time.time()
    key = str(path)
    if key in _PROBE_CACHE and now - _PROBE_CACHE[key][0] < 60:
        return _PROBE_CACHE[key][1]
    info = {"w": 0, "h": 0, "dur": 0.0, "codec": "", "fps": ""}
    try:
        err = subprocess.run([_FF, "-hide_banner", "-i", key],
                             capture_output=True, text=True, timeout=30).stderr
        m = re.search(r"Video: (\w+).*?(\d{2,5})x(\d{2,5})", err)
        if m:
            info["codec"], info["w"], info["h"] = m.group(1), int(m.group(2)), int(m.group(3))
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", err)
        if m:
            info["dur"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        m = re.search(r"(\d+\.?\d*) fps", err)
        if m:
            info["fps"] = m.group(1)
    except Exception:
        pass
    _PROBE_CACHE[key] = (now, info)
    return info


SIMPLE_PAGE = """<!doctype html><html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ভিডিও বানাও</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"Segoe UI",sans-serif;background:#0b1220;color:#e7eef8;
     display:flex;flex-direction:column;align-items:center;padding:18px 14px 40px}
h1{font-size:22px;margin:10px 0 2px}
.sub{color:#8b9bb4;font-size:13px;margin-bottom:18px;text-align:center}
.card{width:100%;max-width:520px;background:#131c2e;border:1px solid #22304a;border-radius:16px;
      padding:18px;display:flex;flex-direction:column;gap:12px}
input[type=text],input[type=number]{width:100%;padding:14px;border-radius:12px;border:1px solid #2b3d5c;
      background:#0e1626;color:#e7eef8;font-size:15px}
input::placeholder{color:#667b99}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{flex:1;min-width:100px;text-align:center;padding:11px;border-radius:12px;border:1px solid #2b3d5c;
      background:#0e1626;color:#a8bcd8;font-size:13px;cursor:pointer;user-select:none}
.chip.on{background:#1d4ed8;border-color:#3b82f6;color:#fff;font-weight:600}
button{width:100%;padding:16px;border:0;border-radius:14px;font-size:17px;font-weight:700;color:#fff;
       background:linear-gradient(135deg,#2563eb,#7c3aed);cursor:pointer}
button:disabled{opacity:.55}
.hint{font-size:12px;color:#7b8b9e;line-height:1.6}
.out{width:100%;max-width:520px;margin-top:16px;background:#131c2e;border:1px solid #22304a;
     border-radius:16px;padding:14px;font-size:14px;display:none}
.out.show{display:block}
.ok{color:#4ade80}.err{color:#fca5a5}.run{color:#60a5fa}
pre{margin:8px 0 0;max-height:180px;overflow:auto;font-size:11px;color:#93a6c0;white-space:pre-wrap}
a.dl{display:block;margin-top:10px;padding:14px;border-radius:12px;background:#16a34a;color:#fff;
     text-align:center;text-decoration:none;font-weight:700}
video{width:100%;border-radius:12px;margin-top:10px;background:#000}
</style></head><body>
<h1>🎬 ভিডিও বানাও</h1>
<div class="sub">YouTube লিংক দাও — অথবা কীওয়ার্ড লেখো<br>সব ভিডিও ১০৮০ · কপিরাইট-ফ্রি · কোনো টাকা লাগে না</div>

<div class="card">
  <input id="txt" type="text" autocomplete="off"
         placeholder="YouTube লিংক পেস্ট করো — অথবা: rain city night">
  <div class="chips" id="src">
    <div class="chip on" data-v="free">🌿 ১০০% কপিরাইট-ফ্রি</div>
    <div class="chip" data-v="hl">🎬 মূল ভিডিও কাটা</div>
  </div>
  <div class="chips" id="fmt">
    <div class="chip on" data-v="square">📱 ১:১ শর্টস</div>
    <div class="chip" data-v="long">🖥️ ১৬:৯ লম্বা</div>
  </div>
  <div class="chips" id="dur">
    <div class="chip" data-v="15">১৫ সেকেন্ড</div>
    <div class="chip on" data-v="30">৩০ সেকেন্ড</div>
    <div class="chip" data-v="60">৬০ সেকেন্ড</div>
  </div>
  <button id="go">🎬 ভিডিও বানাও</button>
  <div class="hint">লিংক দিলে ভিডিওর <b>বিষয়</b> পড়ে ফ্রি ফুটেজ দিয়ে নতুন ভিডিও বানানো হবে
   (মূল ক্লিপ ব্যবহার হয় না, তাই কপিরাইট-ফ্রি)। কীওয়ার্ড লিখলে সেটার ফুটেজ খোঁজা হবে।</div>
</div>

<div class="out" id="out"></div>

<script>
let fmt='square', dur='30', src='free', cur=null, timer=null;
document.querySelectorAll('#src .chip').forEach(c=>c.onclick=()=>{
  document.querySelectorAll('#src .chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); src=c.dataset.v; swapHint();});
function swapHint(){
  document.getElementById('txt').placeholder = src==='hl'
    ? 'YouTube লিংক পেস্ট করো (ভিডিও থেকে সুন্দর অংশ কাটা হবে)'
    : 'লিংক বা কীওয়ার্ড — ফ্রি ফুটেজ দিয়ে বানাবে (কপিরাইট-ফ্রি)';
  document.querySelector('.hint').innerHTML = src==='hl'
    ? 'লিংকের ভিডিও থেকে <b>নিজে সবচেয়ে সুন্দর অংশ খুঁজে</b> কেটে নেবে (বটের মতো) · ১০৮০ · BGM · থাম্বনেইল'
    : 'ভিডিওর <b>বিষয়</b> পড়ে ফ্রি ফুটেজ দিয়ে নতুন ভিডিও (মূল ক্লিপ ব্যবহার হয় না = সম্পূর্ণ কপিরাইট-ফ্রি)';
}
swapHint();
document.querySelectorAll('#fmt .chip').forEach(c=>c.onclick=()=>{
  document.querySelectorAll('#fmt .chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); fmt=c.dataset.v;});
document.querySelectorAll('#dur .chip').forEach(c=>c.onclick=()=>{
  document.querySelectorAll('#dur .chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); dur=c.dataset.v;});

const out=document.getElementById('out'), btn=document.getElementById('go');
btn.onclick=async()=>{
  const txt=document.getElementById('txt').value.trim();
  if(!txt){document.getElementById('txt').focus();return;}
  btn.disabled=true; out.className='out show';
  out.innerHTML='⏳ শুরু হচ্ছে…';
  try{
    const r=await fetch('/go',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({text:txt,fmt:fmt,dur:dur,src:src})});
    const j=await r.json();
    if(!j.ok){out.innerHTML='<span class="err">❌ '+(j.error||'সমস্যা')+'</span>'; btn.disabled=false; return;}
    cur=j.id; poll();
  }catch(e){out.innerHTML='<span class="err">❌ '+e+'</span>'; btn.disabled=false;}
};
function poll(){
  fetch('/api/jobs').then(r=>r.json()).then(list=>{
    const j=list.find(x=>x.id===cur);
    if(!j){out.innerHTML='<span class="err">জব পাওয়া যায়নি</span>';btn.disabled=false;return;}
    const st=j.status;
    let h='';
    if(st==='done'){
      h='<span class="ok">✅ তৈরি! '+j.res+'</span>';
      h+='<a class="dl" href="/download/'+encodeURIComponent(j.file)+'">⬇️ ডাউনলোড করো</a>';
      h+='<video controls src="/stream/'+encodeURIComponent(j.file)+'"></video>';
      btn.disabled=false;
    }else if(st==='error'){
      h='<span class="err">❌ ব্যর্থ হয়েছে — আবার চেষ্টা করো</span>';
      btn.disabled=false;
    }else{
      h='<span class="run">⏳ ভিডিও তৈরি হচ্ছে… (১-৩ মিনিট)</span>';
      timer=setTimeout(poll,4000);
    }
    h+='<pre>'+(j.log||'')+'</pre>';
    out.innerHTML=h;
  }).catch(()=>{timer=setTimeout(poll,5000);});
}
</script></body></html>"""

def thumb_for(path: Path) -> Path | None:
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    out = THUMB_DIR / (path.stem[:60] + "_" + str(int(path.stat().st_size)) + ".jpg")
    if out.exists():
        return out
    try:
        subprocess.run([_FF, "-y", "-v", "error", "-ss", "1.5", "-i", str(path),
                        "-frames:v", "1", "-vf", "scale=480:-2", str(out)],
                       timeout=60, check=True)
        return out if out.exists() else None
    except Exception:
        return None


def list_videos() -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for d in WATCH_DIRS:
        if not d.exists():
            continue
        for p in d.glob("*.mp4"):
            if p.name.startswith(".") or p.name in seen:
                continue
            # ভাঙা/শূন্য ফাইল (ব্যর্থ জবের অবশিষ্ট) ভল্টে দেখাই না
            try:
                if p.stat().st_size < 100_000:
                    continue
            except OSError:
                continue
            # root-এর শুধু deliver/processed নামের ফাইল নিই, ডজন ডজন টেস্ট-ফাইল নয়
            if d == ROOT and not p.name.startswith(("processed_", "final_")):
                continue
            seen.add(p.name)
            st = p.stat()
            info = probe(p)
            items.append({
                "name": p.name,
                "path": str(p),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "w": info["w"], "h": info["h"],
                "dur": info["dur"], "fps": info["fps"], "codec": info["codec"],
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def human_dur(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ── HTML ────────────────────────────────────────────────────────────────────
PAGE = """<!doctype html>
<html lang="bn"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎬 ভিডিও ভল্ট — ১০৮০ ডাউনলোড</title>
<style>
:root{--bg:#0b1020;--card:#151c2f;--line:#243049;--txt:#e8eefc;--mut:#8fa0bf;
--ok:#22c55e;--bad:#ef4444;--acc:#4f8cff}
*{box-sizing:border-box}
body{max-width:1500px;margin:0 auto;background:radial-gradient(1100px 500px at 20% -10%,#1a2a52 0%,var(--bg) 55%);
color:var(--txt);font:15px/1.5 -apple-system,"Segoe UI",Roboto,"Noto Sans Bengali",sans-serif;
padding:22px 16px 60px}
h1{font-size:23px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:18px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
input[type=search]{flex:1;min-width:200px;background:#101830;border:1px solid var(--line);
color:var(--txt);border-radius:12px;padding:11px 14px;font-size:14px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(260px,300px));justify-content:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;
display:flex;flex-direction:column}
.thumb{aspect-ratio:16/9;background:#0d1424 center/cover no-repeat;display:block;
width:100%;object-fit:cover}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:8px;flex:1}
.name{font-weight:600;font-size:14px;word-break:break-all}
.meta{color:var(--mut);font-size:12.5px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.badge{border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:700}
.b1080{background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.35)}
.bnot{background:rgba(239,68,68,.16);color:#fca5a5;border:1px solid rgba(239,68,68,.35)}
.dl{margin-top:auto;display:flex;gap:8px}
a.btn{flex:1;text-align:center;text-decoration:none;background:var(--acc);color:#fff;
padding:11px;border-radius:11px;font-weight:700;font-size:14px}
a.btn.ghost{background:#1b2437;border:1px solid var(--line);color:var(--txt);flex:0 0 auto;padding:11px 13px}
.empty{text-align:center;color:var(--mut);padding:60px 10px}
h2{font-size:15px;color:var(--mut);font-weight:600;margin:26px 0 10px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin-bottom:18px}
.ptitle{font-weight:700;margin-bottom:10px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.row input[name=url]{flex:1;min-width:240px}
.panel input,.panel select{background:#101830;border:1px solid var(--line);color:var(--txt);
border-radius:10px;padding:10px 12px;font-size:14px}
.panel button{background:var(--acc);border:0;color:#fff;font-weight:700;padding:11px 18px;
border-radius:10px;font-size:14px;cursor:pointer}
.panel label{color:var(--mut);font-size:13px;display:flex;gap:6px;align-items:center}
.job{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:10px}
.job .top{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.job pre{margin:8px 0 0;background:#0c1220;border:1px solid var(--line);border-radius:10px;
padding:9px 11px;max-height:150px;overflow:auto;font-size:12px;color:#9fb3d4;white-space:pre-wrap}
.st{font-size:11.5px;font-weight:700;border-radius:999px;padding:2px 9px}
.st-run{background:rgba(79,140,255,.18);color:#93b8ff;border:1px solid rgba(79,140,255,.4)}
.st-ok{background:rgba(34,197,94,.16);color:#4ade80;border:1px solid rgba(34,197,94,.35)}
.st-err{background:rgba(239,68,68,.16);color:#fca5a5;border:1px solid rgba(239,68,68,.35)}
</style></head><body>
<h1>🎬 ভিডিও ভল্ট</h1>
<div class="sub">অরিজিনাল ফাইল · কম্প্রেশন ছাড়া · __COUNT__টা ভিডিও · __TOTAL__</div>
<form id="newjob" class="panel">
  <div class="ptitle">➕ নতুন ভিডিও বানাও</div>
  <div class="row">
    <select name="source" id="src">
      <option value="youtube">🎬 YouTube লিংক (কপিরাইট ঝুঁকি)</option>
      <option value="free">🌿 কপিরাইট-ফ্রি (Pexels/Commons + CC0 BGM)</option>
    </select>
    <input name="url" type="text" required placeholder="YouTube লিংক পেস্ট করো…" />
    <input name="q" type="text" placeholder="কীওয়ার্ড (ফ্রি মোডে): যেমন rain city" style="display:none">
    <label style="display:flex;gap:6px;align-items:center;font-size:13px;color:#9fd0ff">
      <input type="checkbox" name="auto" value="1"> ✂️ অটো-হাইলাইট (মূল অংশ নিজেই কেটে নেবে, বাকিটা বাদ)
    </label>
    <label style="display:flex;gap:6px;align-items:center;font-size:13px;color:#ffcf9f">
      <input type="checkbox" name="keepaudio" value="1"> 🔊 আসল শব্দ রাখো (নইলে আসল অডিও বাদ, কপিরাইট-নিরাপদ)
    </label>
    <div style="font-size:11px;color:#7b8b9e">YouTube · Facebook · Instagram · TikTok লিংক চলবে। HD-র জন্য <code>cookies.txt</code> রাখো।</div>
    <label id="cc0row" style="display:none;gap:6px;align-items:center;font-size:13px;color:#8fe3a8">
      <input type="checkbox" name="cc0" value="1" checked> শুধু CC0 (শূন্য অ্যাট্রিবিউশন)
    </label>
    <select name="mode">
      <option value="square">১:১ স্কয়ার · ১০৮০</option>
      <option value="long">১৬:৯ লং · ১৯২০×১০৮০</option>
    </select>
  </div>
  <div class="row">
    <label>শুরু <input name="start" value="0" size="7"></label>
    <label>কত সেকেন্ড <input name="dur" value="60" size="7"></label>
    <label><input type="checkbox" name="bgm" value="1" checked> 🎵 BGM</label>
    <label><input type="checkbox" name="meta" value="1" checked> 🤖 AI টাইটেল/SEO</label>
    <label><input type="checkbox" name="thumb" value="1"> 🎨 থাম্বনেইল</label>
    <label title="লিংকের বিষয় পড়ে ফ্রি ফুটেজ দিয়ে নতুন ভিডিও — মূল ক্লিপ ব্যবহার হয় না">
      <input type="checkbox" name="remake" value="1"> 🌿 লিংক → কপিরাইট-ফ্রি ভিডিও</label>
    <button type="submit">শুরু করো</button>
    <span class="meta" id="jobmsg"></span>
  </div>
</form>

<div id="jobs"></div>

<div class="bar">
  <input id="q" type="search" placeholder="🔍 ফাইলের নাম খোঁজো...">
  <span class="meta" id="stat"></span>
</div>
<div class="grid">
__CARDS__
</div>
<script>
const q=document.getElementById('q');
q.addEventListener('input',()=>{
  const v=q.value.toLowerCase();let n=0;
  document.querySelectorAll('.card').forEach(c=>{
    const hit=c.dataset.name.includes(v);c.style.display=hit?'':'none';if(hit)n++;
  });
  document.getElementById('stat').textContent=n+'টা দেখাচ্ছে';
});

// ?url=... থাকলে ফর্মে বসিয়ে দিই (বট থেকে এক ট্যাপে আসার জন্য)
const qp=new URLSearchParams(location.search);
if(qp.get('url')){document.querySelector('#newjob input[name=url]').value=qp.get('url');}
if(qp.get('mode')){document.querySelector('#newjob select[name=mode]').value=qp.get('mode');}

// সোর্স বদলালে ইনপুট বদলাই
const srcSel=document.getElementById('src');
function syncSrc(){
  const free=srcSel.value==='free';
  const u=document.querySelector('#newjob input[name=url]');
  const q=document.querySelector('#newjob input[name=q]');
  u.style.display=free?'none':'';
  u.required=!free;
  q.style.display=free?'':'none';
  q.required=free;
  document.getElementById('cc0row').style.display=free?'flex':'none';
  const au=document.querySelector('#newjob input[name=auto]');
  const dIn=document.querySelector('#newjob input[name=dur]');
  if(dIn) dIn.placeholder = au&&au.checked ? 'মোট কত সেকেন্ড ফাইনাল (যেমন 60)' : 'কত সেকেন্ড (যেমন 30)';
}
srcSel.addEventListener('change',syncSrc); syncSrc();

// নতুন ভিডিও সাবমিট
document.getElementById('newjob').addEventListener('submit', async (e)=>{
  e.preventDefault();
  const f=e.target, msg=document.getElementById('jobmsg');
  msg.textContent='⏳ পাঠানো হচ্ছে…';
  const body=new URLSearchParams(new FormData(f));
  const r=await fetch('/submit',{method:'POST',body});
  const j=await r.json();
  msg.textContent = j.ok ? '✅ শুরু হয়েছে — নিচে অগ্রগতি দেখো' : ('❌ '+j.error);
  if(j.ok) f.reset();
  poll();
});

async function poll(){
  try{
    const r=await fetch('/api/jobs'); const jobs=await r.json();
    document.getElementById('jobs').innerHTML = jobs.map(j=>`
      <div class="job">
        <div class="top">
          <span class="st ${j.status==='done'?'st-ok':(j.status==='error'?'st-err':'st-run')}">${j.label}</span>
          <b>${j.title||j.id}</b>
          <span class="meta">${j.mode==='long'?'১৬:৯':'১:১'} · ${j.dur}s</span>
          ${j.status==='done'?`<a class="btn" style="max-width:150px" href="/download/${encodeURIComponent(j.file)}">⬇️ ডাউনলোড</a>`:''}
        </div>
        <pre>${(j.log||'').slice(-1200)}</pre>
      </div>`).join('');
  }catch(e){}
}
poll(); setInterval(poll, 4000);
</script>
</body></html>"""

CARD = """<div class="card" data-name="{name_l}">
  <img class="thumb" loading="lazy" src="{thumb}" alt="">
  <div class="body">
    <div class="name">{name}</div>
    <div class="meta">
      <span class="badge {cls}">{res}</span>
      <span>{size}</span><span>·</span><span>{dur}</span><span>·</span><span>{fps}fps</span>
    </div>
    <div class="meta">{when}</div>
    <div class="dl">
      <a class="btn" href="/download/{qname}">⬇️ ডাউনলোড</a>
      <a class="btn ghost" href="/stream/{qname}" target="_blank">▶️</a>
      <a class="btn cut" href="/cut?name={qname}">✂️ কাট</a>
    </div>
  </div>
</div>"""


# ── কাজ (job) ব্যবস্থাপনা ───────────────────────────────────────────────────
JOBS_DIR = ROOT / "web" / ".jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = JOBS_DIR / "jobs.json"
_JOBS: dict[str, dict] = {}


def _load_jobs() -> None:
    if JOBS_FILE.exists():
        try:
            _JOBS.update(json.loads(JOBS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass


def _save_jobs() -> None:
    """অ্যাটমিক রাইট — প্রসেস হঠাৎ মরলেও jobs.json নষ্ট হবে না।"""
    try:
        tmp = JOBS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_JOBS, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, JOBS_FILE)
    except Exception:
        pass


def _recover_from_disk() -> None:
    """deliver/-এ থাকা ভিডিও কিন্তু হিস্ট্রিতে নেই → ফিরিয়ে আনি (হারায় না)।"""
    try:
        for f in sorted((ROOT / "deliver").glob("*.mp4")):
            if not f.is_file() or f.stat().st_size < 200_000:
                continue
            nm = f.stem
            if any(v.get("file") == f.name for v in _JOBS.values()):
                continue
            jid = nm.replace("web_", "").replace("processed_", "")
            if jid in _JOBS:
                continue
            log_path = JOBS_DIR / f"{jid}.log"
            if not log_path.exists():
                log_path.write_text(f"DONE {f.name}\n", encoding="utf-8")
            _JOBS[jid] = {"id": jid, "title": f.name, "mode": "", "dur": "",
                          "log": str(log_path), "pid": 0, "rc": 0,
                          "started": f.stat().st_mtime, "finished": f.stat().st_mtime}
    except Exception:
        pass


def _reap_dead_jobs() -> None:
    """
    প্রসেস মরে গেছে কিন্তু rc লেখা হয়নি → জব চিরকাল 'running' থাকে,
    ফলে "একটা কাজ এখনো চলছে" বলে নতুন জব শুরুই হতো না (ব্যবহারকারীর অভিযোগ)।
    """
    for jid, j in list(_JOBS.items()):
        if j.get("rc") is not None:
            continue
        pid = int(j.get("pid") or 0)
        if pid <= 0:
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            j["rc"] = -99
            j["finished"] = time.time()
            try:
                lp = Path(j["log"])
                with open(lp, "a", encoding="utf-8") as f:
                    f.write("\n❌ প্রসেস আর চলছে না (watchdog) — আবার চেষ্টা করো\n")
            except Exception:
                pass


def _job_state(j: dict) -> dict:
    """লগ-ফাইল পড়ে অবস্থা/অগ্রগতি বের করে।"""
    log_path = Path(j["log"])
    text = ""
    if log_path.exists():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
    status, file_name, res = "running", "", ""
    title, desc, thumb = "", "", ""
    for line in text.splitlines():
        if line.startswith("TITLE "):
            title = line[6:].strip()
        elif line.startswith("DESC "):
            desc = line[5:].strip()
        elif line.startswith("THUMB "):
            thumb = line[6:].strip()
            # লগে শুধু ফাইলনাম থাকে → ব্রাউজারে খোলার মতো URL বানাই
            if thumb and not thumb.startswith(("/", "http")):
                if (ROOT / "deliver" / thumb).exists():
                    thumb = "/dl/" + urllib.parse.quote(thumb)
    if "DONE " in text:
        status = "done"
        tail = text.rsplit("DONE ", 1)[1].splitlines()[0].split()
        file_name = tail[0] if tail else ""
        res = f"{tail[1]}×{tail[2]}" if len(tail) >= 3 else ""
    elif j.get("rc") not in (None, 0):
        status = "error"
    elif j.get("rc") == 0 and "DONE " not in text:
        status = "error"
    return {
        "id": j["id"],
        "title": j.get("title", ""),
        "mode": j.get("mode", "square"),
        "dur": j.get("dur", ""),
        "status": status,
        "file": file_name,
        "res": res,
        "ai_title": title,
        "desc": desc,
        "thumb": thumb,
        "log": text,
        "label": {"running": "⏳ চলছে", "done": "✅ তৈরি", "error": "❌ ব্যর্থ"}[status],
    }


VIDEO_HOSTS = (
    "youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com",
    "facebook.com", "fb.watch", "m.facebook.com", "web.facebook.com",
    "instagram.com", "instagr.am", "tiktok.com", "vm.tiktok.com",
    "twitter.com", "x.com", "vimeo.com", "dailymotion.com", "dai.ly",
    "twitch.tv", "reddit.com", "redd.it", "bilibili.com",
)


def check_link(url: str) -> None:
    """
    লিংক সত্যিই ভিডিও সাইটের কি না — না হলে সাথে সাথে পরিষ্কার এরর।
    আগে GitHub/ব্লগ লিংক দিলে yt-dlp ৮ বার চেষ্টা করে সময় নষ্ট করত।
    """
    u = (url or "").strip()
    if not u:
        raise ValueError("লিংক দাও")
    if u == "free" or u.startswith(("/", "file://")):
        return
    low = u.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        raise ValueError("লিংকটি http(s):// দিয়ে শুরু হতে হবে")
    pr = urllib.parse.urlparse(low)
    host = pr.netloc.replace("www.", "")
    path = pr.path or "/"

    # চ্যানেল/প্রোফাইল/প্লেলিস্ট/সার্চ পেজ ভিডিও নয় — সাথে সাথে বাদ
    bad_prefix = ("/@", "/channel/", "/user/", "/c/", "/playlist",
                  "/results", "/feed", "/hashtag/", "/explore/", "/search")
    if path.startswith(bad_prefix):
        raise ValueError("এটা চ্যানেল/প্রোফাইল/প্লেলিস্ট লিংক — নির্দিষ্ট ভিডিওর লিংক দাও "
                         "(যেমন youtube.com/watch?v=… বা facebook.com/watch?v=…)")
    if "youtube.com" in host and not path.startswith(("/watch", "/shorts/", "/live/", "/embed/")):
        raise ValueError("YouTube ভিডিও লিংক দাও — youtube.com/watch?v=… বা /shorts/…")
    if "facebook" in host and not path.startswith(("/watch", "/reel", "/videos/", "/video")):
        if "fb.watch" not in host:
            raise ValueError("Facebook ভিডিও লিংক দাও — /watch?v=… বা /reel/…")

    if not any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS):
        raise ValueError(
            f"'{host}' ভিডিও সাইট নয় — YouTube / Facebook / Instagram / TikTok "
            f"লিংক দাও (ভিডিও পেজের লিংক, চ্যানেল/প্রোফাইল নয়)")


def check_disk(need_gb: float = 2.0) -> None:
    """
    ডিস্কে জায়গা আছে কি না — না থাকলে জব শুরুর আগেই থামাই।
    ১০ মিনিটের ১০৮০ ভিডিও নামাতে + প্রসেস করতে ~১ GB দরকার হয়।
    """
    try:
        st = os.statvfs(str(ROOT))
        free_gb = st.f_bavail * st.f_frsize / 1e9
    except Exception:
        return
    if free_gb < need_gb:
        raise ValueError(
            f"ডিস্কে মাত্র {free_gb:.1f} GB খালি — ভিডিও বানাতে অন্তত {need_gb:.0f} GB দরকার। "
            f"~/Downloads বা ~/Documents থেকে কিছু ফাইল সরাও, তারপর আবার চেষ্টা করো।")


def start_job(url: str, mode: str, start: str, dur: str,
              flags: list[str] | None = None, out_name: str | None = None) -> dict:
    _reap_dead_jobs()
    if _JOBS and any(_job_state(j)["status"] == "running" for j in _JOBS.values()):
        return {"ok": False, "error": "একটা কাজ এখনো চলছে — শেষ হলে আবার চেষ্টা করো"}
    jid = time.strftime("%H%M%S")
    name = out_name or f"web_{jid}"
    log_path = JOBS_DIR / f"{jid}.log"
    cmd = [sys.executable, str(ROOT / "web" / "worker.py"),
           url, mode, start, dur, str(ROOT / "deliver"), name] + (flags or [])
    fh = open(log_path, "wb")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
    _JOBS[jid] = {
        "id": jid, "title": url[:60], "mode": mode, "dur": dur,
        "log": str(log_path), "pid": proc.pid, "rc": None,
        "started": time.time(),
    }
    _save_jobs()
    threading.Thread(target=_wait_job, args=(jid, proc), daemon=True).start()
    return {"ok": True, "id": jid}


def _wait_job(jid: str, proc: subprocess.Popen) -> None:
    rc = proc.wait()
    if jid in _JOBS:
        _JOBS[jid]["rc"] = rc
        _JOBS[jid]["finished"] = time.time()
        _save_jobs()




CUT_PAGE = """<!doctype html><html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>✂️ ম্যানুয়াল কাটার — ভিডিও ভল্ট</title>
<style>
 body{margin:0;background:#0b0f14;color:#e8eef6;font:15px/1.5 -apple-system,Segoe UI,sans-serif}
 header{padding:14px 18px;border-bottom:1px solid #1c2634;display:flex;gap:12px;align-items:center}
 h1{font-size:17px;margin:0;font-weight:600}
 a{color:#7cc4ff;text-decoration:none}
 .wrap{max-width:960px;margin:0 auto;padding:18px}
 video{width:100%;border-radius:12px;background:#000;display:block}
 .bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;align-items:center}
 input[type=range]{flex:1;min-width:160px;accent-color:#3fa9ff}
 input[type=text],input[type=number],select{background:#131c26;border:1px solid #24333f;color:#e8eef6;
   padding:8px 10px;border-radius:8px;font-size:14px;width:110px}
 button{background:#1d6ff2;color:#fff;border:0;padding:9px 16px;border-radius:9px;font-size:14px;cursor:pointer}
 button.ghost{background:#182430;border:1px solid #24333f}
 .box{margin-top:16px;background:#101821;border:1px solid #1c2634;border-radius:12px;padding:14px}
 .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:8px 0}
 .hint{color:#7b8b9e;font-size:12px}
 #log{white-space:pre-wrap;font:12px/1.45 ui-monospace,monospace;color:#9fb3c8;max-height:220px;overflow:auto}
 .sel{color:#8fe3a8;font-weight:600}
</style></head><body>
<header><h1>✂️ ম্যানুয়াল কাটার</h1><a href="/">← ভল্টে ফিরি</a>
 <span class="hint" id="fname">__NAME__</span></header>
<div class="wrap">
 <video id="v" controls preload="metadata" src="/stream/__QNAME__"></video>
 <div class="bar">
   <span class="hint">শুরু</span><input type="text" id="t0" value="0:00">
   <span class="hint">শেষ</span><input type="text" id="t1" value="0:15">
   <span class="sel" id="len">—</span>
 </div>
 <div class="bar">
   <input type="range" id="r0" min="0" max="100" step="0.1" value="0">
 </div>
 <div class="bar">
   <input type="range" id="r1" min="0" max="100" step="0.1" value="15">
 </div>
 <div class="bar">
   <button class="ghost" onclick="mark(0)">⏱ শুরু এখানে</button>
   <button class="ghost" onclick="mark(1)">⏱ শেষ এখানে</button>
   <button class="ghost" onclick="preview()">▶️ সিলেকশন দেখাও</button>
 </div>
 <div class="box">
   <div class="row">
     <label>ধরন</label>
     <select id="mode"><option value="square">১:১ শর্টস (১০৮০×১০৮০)</option>
       <option value="long">১৬:৯ লং (১৯২০×১০৮০)</option></select>
     <label><input type="checkbox" id="bgm"> BGM</label>
     <button onclick="go()">✂️ কাট করে বানাও</button>
   </div>
   <div class="hint">কাটার পর একই পাইপলাইন চলবে — বার-মুক্ত ক্রপ, ১০৮০, ট্র্যাকিং।</div>
   <div id="log"></div>
 </div>
</div>
<script>
const v=document.getElementById('v'), t0=document.getElementById('t0'), t1=document.getElementById('t1'),
      r0=document.getElementById('r0'), r1=document.getElementById('r1'),
      len=document.getElementById('len'), log=document.getElementById('log');
let D=0;
v.addEventListener('loadedmetadata',()=>{D=v.duration||0;r0.max=r1.max=D;
  t1.value=fmt(Math.min(15,D)); r1.value=Math.min(15,D); upd();});
function fmt(x){x=Math.max(0,x||0);const m=Math.floor(x/60),s=Math.round(x%60);
  return m+':'+String(s).padStart(2,'0');}
function parse(x){if(!x)return 0;x=String(x).trim();if(x.includes(':')){const p=x.split(':');
  return (+p[0]||0)*60+(+p[1]||0);}return +x||0;}
function upd(){const a=parse(t0.value),b=parse(t1.value);
  len.textContent='নির্বাচিত: '+(Math.max(0,b-a)).toFixed(1)+'s';}
[r0,r1].forEach(r=>r.addEventListener('input',()=>{
  if(r===r0){t0.value=fmt(+r.value); if(+r0.value>+r1.value-0.5){r1.value=+r0.value+0.5;t1.value=fmt(+r1.value);}}
  else {t1.value=fmt(+r.value); if(+r1.value<+r0.value+0.5){r0.value=+r1.value-0.5;t0.value=fmt(+r0.value);}}
  upd();}));
[t0,t1].forEach(i=>i.addEventListener('input',()=>{r0.value=parse(t0.value);r1.value=parse(t1.value);upd();}));
function mark(which){const cur=v.currentTime||0;
  if(which===0){t0.value=fmt(cur);r0.value=cur;}else{t1.value=fmt(cur);r1.value=cur;}upd();}
function preview(){v.currentTime=parse(t0.value);v.play();
  const b=parse(t1.value);
  const stop=()=>{if(v.currentTime>=b){v.pause();v.removeEventListener('timeupdate',stop);}};
  v.addEventListener('timeupdate',stop);}
async function go(){
  const a=parse(t0.value), b=parse(t1.value);
  if(b-a<1){log.textContent='❌ অন্তত ১ সেকেন্ড দরকার';return;}
  log.textContent='⏳ জমা দেওয়া হচ্ছে…';
  const body=new URLSearchParams({name:'__NAME__',start:String(a),dur:String(b-a),
    mode:document.getElementById('mode').value,bgm:document.getElementById('bgm').checked?'1':''});
  const r=await fetch('/trim',{method:'POST',body});
  const j=await r.json();
  if(!j.ok){log.textContent='❌ '+j.error;return;}
  log.textContent='✅ জব শুরু: '+j.id+'\n';
  const t=setInterval(async()=>{
    const rr=await fetch('/api/jobs'); const arr=await rr.json();
    const job=arr.find(x=>x.id===j.id); if(!job)return;
    log.textContent='✅ জব '+j.id+' ['+job.status+']\n'+job.log.split('\n').slice(-12).join('\n');
    if(job.status==='done'||job.status==='error'){clearInterval(t);
      if(job.status==='done'){log.textContent+='\n\n🎬 তৈরি: '+job.file+' → ভল্টে দেখো';}}
  },2000);
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoVault/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _file(self, path: Path, download: bool):
        if not path.exists() or not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        if download:
            fn = urllib.parse.quote(path.name)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{fn}")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1024 * 512)

    def _do_trim(self):
        """✂️ ম্যানুয়াল কাট — ভল্টের ফাইল থেকে নির্দিষ্ট অংশ প্রসেস করে নতুন ভিডিও।"""
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(min(n, 64 * 1024)).decode("utf-8", "replace")
            form = urllib.parse.parse_qs(body)
            name = (form.get("name", [""])[0] or "").strip()
            start = float(form.get("start", ["0"])[0] or 0)
            dur = float(form.get("dur", ["0"])[0] or 0)
            mode = form.get("mode", ["square"])[0]
            flags = ["--bgm"] if form.get("bgm", [""])[0] == "1" else []
            if not name or dur < 1:
                raise ValueError("ফাইল/দৈর্ঘ্য ঠিক নেই")
            src = None
            for d in WATCH_DIRS:
                cand = d / name
                if cand.exists() and cand.suffix == ".mp4":
                    src = cand
                    break
            if not src:
                raise ValueError("ফাইল পাওয়া যায়নি")
            stamp = time.strftime("%H%M%S")
            out_name = f"cut_{stamp}"
            res = start_job(str(src), mode, f"{start:.2f}", f"{dur:.2f}", flags,
                            out_name=out_name)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/trim":
            self._do_trim()
            return
        if u.path not in ("/submit", "/go"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(min(n, 64 * 1024)).decode("utf-8", "replace")
            form = urllib.parse.parse_qs(body)

            # ── সরল পাতা (/go): এক ইনপুট — লিংক নাকি কীওয়ার্ড, নিজেই বুঝে নেয় ──
            if u.path == "/go":
                text = (form.get("text", [""])[0] or "").strip()
                fmt = (form.get("fmt", ["square"])[0] or "square")
                gsrc = (form.get("src", ["free"])[0] or "free")
                gdur = (form.get("dur", ["30"])[0] or "30")
                if not text:
                    res = {"ok": False, "error": "লিংক বা কীওয়ার্ড দাও"}
                else:
                    check_disk(2.0)
                    gmode = "long" if fmt == "long" else "square"
                    if gsrc == "free":
                        # ফ্রি ফুটেজ: লিংক হলে বিষয় পড়ে, শব্দ হলে কীওয়ার্ড
                        if text.startswith(("http://", "https://", "www.")):
                            res = start_job(text, gmode, "0", gdur,
                                            ["--remake", "--free", "--bgm"])
                        else:
                            res = start_job("free", gmode, "0", gdur,
                                            ["--free", "--bgm", "--q=" + text])
                    else:
                        # হাইলাইট: বটের মতো — মূল ভিডিও থেকে সুন্দর অংশ কাটে
                        if not text.startswith(("http://", "https://", "www.")):
                            res = {"ok": False, "error": "হাইলাইট মোডে YouTube লিংক দাও"}
                        else:
                            check_link(text)
                            res = start_job(text, gmode, "0", gdur,
                                            ["--auto", "--bgm", "--meta", "--thumb"])
                self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
                return

            url = (form.get("url", [""])[0] or "").strip()
            _src = form.get("source", ["youtube"])[0]
            if _src == "free" and not url:
                url = "free"
            mode = form.get("mode", ["square"])[0]
            start = form.get("start", ["0"])[0]
            dur = form.get("dur", ["60"])[0]
            if not url:
                raise ValueError("লিংক দাও")
            check_link(url)
            check_disk(2.0)
            flags = []
            if form.get("auto", [""])[0] == "1":
                flags.append("--auto")
                if form.get("keepaudio", [""])[0] == "1":
                    flags.append("--keep-audio")
            if form.get("remake", [""])[0] == "1" and url.startswith("http"):
                flags.append("--remake")
                flags.append("--free")
                if "--bgm" not in flags:
                    flags.append("--bgm")
                log_note = "remake"
            if form.get("source", ["youtube"])[0] == "free":
                flags.append("--free")
                if form.get("cc0", [""])[0] != "1":
                    flags.append("--any-license")
                flags.append("--q=" + (form.get("q", ["nature"])[0] or "nature cinematic"))
                if not url:
                    url = "free"
            if form.get("bgm", [""])[0] == "1":
                flags.append("--bgm")
            if form.get("meta", [""])[0] == "1":
                flags.append("--meta")
            if form.get("thumb", [""])[0] == "1":
                flags.append("--thumb")
            res = start_job(url, mode, start, dur, flags)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):  # noqa: C901
        u = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(u.path)

        if path == "/":
            self._send(200, SIMPLE_PAGE.encode("utf-8"),
                       "text/html; charset=utf-8", {"Cache-Control": "no-store"})
            return

        if path == "/pro":
            vids = list_videos()
            cards = []
            for v in vids:
                t = thumb_for(Path(v["path"]))
                is1080 = v["h"] >= 1080 or v["w"] >= 1080
                cards.append(CARD.format(
                    name=html.escape(v["name"]),
                    name_l=html.escape(v["name"].lower()),
                    thumb=f"/thumb/{urllib.parse.quote(v['name'])}" if t else "",
                    cls="b1080" if is1080 else "bnot",
                    res=html.escape(f"{v['w']}×{v['h']}" if v["w"] else "?"),
                    size=human_size(v["size"]),
                    dur=human_dur(v["dur"]),
                    fps=html.escape(v["fps"] or "?"),
                    when=time.strftime("%Y-%m-%d %H:%M", time.localtime(v["mtime"])),
                    qname=urllib.parse.quote(v["name"]),
                ))
            body = (PAGE
                    .replace("__COUNT__", str(len(vids)))
                    .replace("__TOTAL__", human_size(sum(v["size"] for v in vids)))
                    .replace("__CARDS__", "\n".join(cards) or
                             '<div class="empty">এখনো কোনো ভিডিও নেই।<br>'
                             'উপরে লিংক দিয়ে প্রথম ভিডিও বানাও।</div>'))
            self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/cut":
            q = urllib.parse.parse_qs(u.query)
            name = (q.get("name", [""])[0] or "").strip()
            found = None
            for d in WATCH_DIRS:
                cand = d / name
                if cand.exists() and cand.suffix == ".mp4":
                    found = cand
                    break
            if not found:
                self._send(404, b"video not found", "text/plain; charset=utf-8")
                return
            body = (CUT_PAGE.replace("__NAME__", html.escape(name))
                            .replace("__QNAME__", urllib.parse.quote(name)))
            self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path.startswith("/api/jobs"):
            _reap_dead_jobs()
            data = json.dumps([_job_state(j) for j in
                               sorted(_JOBS.values(), key=lambda x: x.get("started", 0), reverse=True)],
                              ensure_ascii=False).encode("utf-8")
            self._send(200, data, "application/json; charset=utf-8")
            return

        if path.startswith("/api/list"):
            data = json.dumps(list_videos(), ensure_ascii=False).encode("utf-8")
            self._send(200, data, "application/json; charset=utf-8")
            return

        for prefix, download in (("/download/", True), ("/stream/", False)):
            if path.startswith(prefix):
                name = path[len(prefix):]
                for d in WATCH_DIRS:
                    cand = d / name
                    if cand.exists() and cand.suffix == ".mp4":
                        self._file(cand, download)
                        return
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return

        if path.startswith("/dl/"):
            name = os.path.basename(urllib.parse.unquote(path[len("/dl/"):]))
            cand = ROOT / "deliver" / name
            if cand.exists() and cand.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                ctype = "image/jpeg" if cand.suffix.lower() in (".jpg", ".jpeg") else f"image/{cand.suffix[1:]}"
                self._send(200, cand.read_bytes(), ctype)
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return

        if path.startswith("/thumb/"):
            name = path[len("/thumb/"):]
            for d in WATCH_DIRS:
                cand = d / name
                if cand.exists():
                    t = thumb_for(cand)
                    if t:
                        self._send(200, t.read_bytes(), "image/jpeg")
                        return
            self._send(404, b"no thumb", "text/plain; charset=utf-8")
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("VAULT_PORT", PORT)))
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    ThreadingHTTPServer.allow_reuse_address = True
    _load_jobs()            # আগের হিস্ট্রি ফিরিয়ে আনি
    _recover_from_disk()    # deliver/-এ থাকা ভিডিওও তালিকায় আসে
    _save_jobs()
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    url = f"http://{lan_ip()}:{args.port}"
    print(f"🌐 ভিডিও ভল্ট চালু → {url}   (এই মেশিনে: http://127.0.0.1:{args.port})")
    for d in WATCH_DIRS:
        print(f"   দেখছে: {d}")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nবন্ধ করা হলো।")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
