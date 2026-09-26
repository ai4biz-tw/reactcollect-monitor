#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReactCollect 補貨監控（本機網頁版）
- 雙擊 run.bat / run.sh 即會在本機開一個網頁（http://localhost:8787）
- 貼上 reactcollect.com 商品連結即可加入追蹤
- 每 15 分鐘自動檢查一次追蹤中的商品，有「缺貨 -> 有貨」變化就記進事件紀錄
- 純 Python 標準函式庫，不需 pip 安裝任何套件
"""
import json
import re
import time
import threading
import urllib.request
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta

PORT = 8787
DATA_FILE = "data.json"
CHECK_INTERVAL = 15 * 60  # 秒
ALLOWED_HOSTS = ("reactcollect.com", "www.reactcollect.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TZ = timezone(timedelta(hours=8))  # 台灣時間

STATUS_LABEL = {
    "in_stock": "有貨",
    "out_of_stock": "缺貨",
    "preorder": "預購中",
    "limited": "限量供應",
    "unknown": "未知",
}

_lock = threading.Lock()


# ---------- 資料儲存 ----------

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            d.setdefault("products", [])
            d.setdefault("events", [])
            d.setdefault("next_id", 1)
            return d
    except (FileNotFoundError, json.JSONDecodeError):
        return {"products": [], "events": [], "next_id": 1}


def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


# ---------- 抓取 ----------

def normalize_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("請貼上商品連結")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    if p.hostname not in ALLOWED_HOSTS:
        raise ValueError("目前只支援 reactcollect.com 的商品連結")
    if not p.path.startswith("/products/"):
        raise ValueError("請貼上 ReactCollect 的商品頁連結（/products/...）")
    return "https://" + p.hostname + p.path


def normalize_availability(raw):
    s = (raw or "").lower()
    if "outofstock" in s or "soldout" in s:
        return "out_of_stock"
    if "limitedavailability" in s:
        return "limited"
    if "preorder" in s:
        return "preorder"
    if "instock" in s:
        return "in_stock"
    return "unknown"


def fetch_snapshot(url):
    """抓商品頁，回傳 dict；失敗時 status=unknown 且帶 error 訊息"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html_text = r.read().decode("utf-8", "replace")
    except Exception as e:
        return {"status": "unknown", "error": "連線失敗：%s" % e,
                "name": "", "price": None, "currency": "TWD", "image": ""}

    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html_text, re.S | re.I)
    for block in blocks:
        try:
            data = json.loads(block)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict) or it.get("@type") != "Product":
                continue
            offers = it.get("offers", {}) or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            raw = str(offers.get("availability", ""))
            img = it.get("image", "")
            if isinstance(img, list):
                img = img[0] if img else ""
            return {
                "name": it.get("name", ""),
                "price": offers.get("price"),
                "currency": offers.get("priceCurrency", "TWD"),
                "availability_raw": raw,
                "status": normalize_availability(raw),
                "image": img if isinstance(img, str) else "",
                "sku": it.get("sku", ""),
                "error": "",
            }
    return {"status": "unknown", "error": "頁面解析失敗（找不到商品資料）",
            "name": "", "price": None, "currency": "TWD", "image": ""}


# ---------- 檢查邏輯 ----------

def check_product(d, prod):
    snap = fetch_snapshot(prod["url"])
    old = prod.get("status", "unknown")
    new = snap["status"]
    prod["last_checked"] = now_iso()
    if snap.get("error"):
        prod["last_error"] = snap["error"]
        return None  # 失敗不發事件、不改狀態，避免假警報
    prod["last_error"] = ""
    prod["name"] = snap["name"] or prod.get("name", "")
    prod["price"] = snap["price"]
    prod["currency"] = snap["currency"]
    if snap.get("image"):
        prod["image"] = snap["image"]
    event = None
    if old != new:
        prod["status"] = new
        event = {"ts": now_iso(), "product_id": prod["id"],
                 "name": prod.get("name", ""), "from": old, "to": new,
                 "price": snap["price"]}
        d["events"].insert(0, event)
        d["events"] = d["events"][:200]
    return event


def check_all():
    with _lock:
        d = load_data()
        for p in d["products"]:
            if p.get("tracking", True):
                check_product(d, p)
                time.sleep(1)
        save_data(d)


def background_loop(stop_event):
    while not stop_event.wait(CHECK_INTERVAL):
        try:
            check_all()
        except Exception:
            pass


# ---------- HTTP ----------

PAGE = """<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReactCollect 補貨監控</title>
<style>
body{font-family:-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif;
  max-width:860px;margin:0 auto;padding:20px;background:#f6f6f8;color:#222}
h1{font-size:22px} .card{background:#fff;border-radius:12px;padding:14px;
  margin:12px 0;display:flex;gap:12px;align-items:center;
  box-shadow:0 1px 4px rgba(0,0,0,.06)}
.card img{width:72px;height:72px;object-fit:cover;border-radius:8px;background:#eee}
.info{flex:1;min-width:0} .name{font-weight:700;margin-bottom:4px}
.meta{color:#666;font-size:13px}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:13px;
  font-weight:700;margin-left:6px}
.in_stock{background:#e6f7e6;color:#137333} .out_of_stock{background:#fde8e8;color:#b3261e}
.preorder{background:#fff4d6;color:#8a5a00} .limited{background:#e8f0fe;color:#1a56db}
.unknown{background:#eee;color:#666}
.btn{border:1px solid #ddd;background:#fff;border-radius:8px;padding:7px 12px;
  cursor:pointer;font-size:14px;margin-right:6px}
.btn:hover{background:#f0f0f0} .btn.primary{background:#1a73e8;color:#fff;border:none}
.btn.primary:hover{background:#1765cc}
.row{display:flex;gap:8px;margin:14px 0}
input[type=text]{flex:1;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:15px}
.event{background:#fff;border-radius:8px;padding:10px 14px;margin:8px 0;font-size:14px;
  box-shadow:0 1px 3px rgba(0,0,0,.05)}
.event.restock{border-left:5px solid #137333}
small.hint{color:#888}
</style></head><body>
<h1>🛒 ReactCollect 補貨監控</h1>
<p><small class="hint">每 15 分鐘自動檢查一次追蹤中的商品。有「缺貨 → 有貨」會記在事件紀錄並跳通知。</small></p>
<div class="row">
<input id="url" type="text" placeholder="貼上 reactcollect.com 商品頁連結…">
<button class="btn primary" onclick="addProduct()">加入追蹤</button>
<button class="btn" onclick="checkNow()">立即檢查全部</button>
</div>
<div id="list"></div>
<h2>📝 事件紀錄</h2>
<div id="events"></div>
<script>
let lastSeenRestock = null;
async function api(path, body){
  const r = await fetch(path,{method:body?"POST":"GET",
    headers:{"Content-Type":"application/json"},
    body:body?JSON.stringify(body):undefined});
  return r.json();
}
function badge(s){
  const label={"in_stock":"有貨 ✅","out_of_stock":"缺貨","preorder":"預購中",
    "limited":"限量供應","unknown":"未知"}[s]||s;
  return `<span class="badge ${s}">${label}</span>`;
}
async function refresh(){
  const d = await api("/api/state");
  const list = document.getElementById("list");
  list.innerHTML = d.products.map(p=>`
    <div class="card">
      ${p.image?`<img src="${p.image}">`:""}
      <div class="info">
        <div class="name">${esc(p.name||"(名稱讀取中)")}${badge(p.status)}</div>
        <div class="meta">${p.price?("NT$ "+Number(p.price).toLocaleString()):""}
          · 上次檢查：${p.last_checked||"—"}${p.last_error?(" · ⚠ "+esc(p.last_error)):""}</div>
      </div>
      <div>
        <button class="btn" onclick="toggleP(${p.id},${!p.tracking})">${p.tracking?"⏸ 暫停":"▶ 恢復"}</button>
        <button class="btn" onclick="checkOne(${p.id})">🔄</button>
        <button class="btn" onclick="removeP(${p.id})">🗑</button>
        <a class="btn" href="${p.url}" target="_blank" style="text-decoration:none">🔗</a>
      </div>
    </div>`).join("") || "<p>還沒有追蹤任何商品，貼上連結開始吧。</p>";
  const ev = document.getElementById("events");
  ev.innerHTML = d.events.map(e=>{
    const restock = e.from==="out_of_stock"&&e.to==="in_stock";
    const txt=`${e.ts}｜${esc(e.name)}：${st(e.from)} → ${st(e.to)}`;
    return `<div class="event${restock?" restock":""}">${restock?"🚨 補貨了！":"ℹ️ "}${txt}</div>`;
  }).join("") || "<p>尚無事件。</p>";
  const newest = d.events.find(e=>e.from==="out_of_stock"&&e.to==="in_stock");
  if(newest && newest.ts!==lastSeenRestock){
    if(lastSeenRestock && Notification.permission==="granted")
      new Notification("🚨 補貨了！",{body:newest.name});
    lastSeenRestock = newest.ts;
  }
}
function st(s){return {"in_stock":"有貨","out_of_stock":"缺貨","preorder":"預購中",
  "limited":"限量供應","unknown":"未知"}[s]||s;}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
async function addProduct(){
  const url=document.getElementById("url").value;
  const r=await api("/api/add",{url});
  if(r.error) alert(r.error); else document.getElementById("url").value="";
  refresh();
}
async function toggleP(id,tracking){await api("/api/toggle",{id,tracking});refresh();}
async function removeP(id){if(confirm("確定移除追蹤？")){await api("/api/remove",{id});refresh();}}
async function checkOne(id){await api("/api/check",{id});refresh();}
async function checkNow(){await api("/api/check",{});refresh();}
if("Notification" in window && Notification.permission==="default") Notification.requestPermission();
refresh(); setInterval(refresh,30000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            with _lock:
                d = load_data()
                self._json({"products": d["products"], "events": d["events"]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._body()
        except Exception:
            return self._json({"error": "請求格式錯誤"}, 400)

        if self.path == "/api/add":
            try:
                url = normalize_url(body.get("url", ""))
            except ValueError as e:
                return self._json({"error": str(e)})
            snap = fetch_snapshot(url)
            if snap.get("error"):
                return self._json({"error": "讀不到這個商品頁：%s" % snap["error"]})
            with _lock:
                d = load_data()
                if any(p["url"] == url for p in d["products"]):
                    return self._json({"error": "這個商品已經在追蹤清單裡了"})
                pid = d["next_id"]
                d["next_id"] += 1
                d["products"].append({
                    "id": pid, "url": url, "name": snap["name"],
                    "price": snap["price"], "currency": snap["currency"],
                    "image": snap["image"], "status": snap["status"],
                    "tracking": True, "added_at": now_iso(),
                    "last_checked": now_iso(), "last_error": "",
                })
                save_data(d)
            threading.Thread(target=check_all, daemon=True).start()
            return self._json({"ok": True})

        if self.path == "/api/toggle":
            with _lock:
                d = load_data()
                for p in d["products"]:
                    if p["id"] == body.get("id"):
                        p["tracking"] = bool(body.get("tracking", True))
                save_data(d)
            return self._json({"ok": True})

        if self.path == "/api/remove":
            with _lock:
                d = load_data()
                d["products"] = [p for p in d["products"] if p["id"] != body.get("id")]
                save_data(d)
            return self._json({"ok": True})

        if self.path == "/api/check":
            pid = body.get("id")
            def run():
                with _lock:
                    d = load_data()
                    targets = [p for p in d["products"]
                               if pid is None or p["id"] == pid]
                    for p in targets:
                        if p.get("tracking", True):
                            check_product(d, p)
                            time.sleep(1)
                    save_data(d)
            threading.Thread(target=run, daemon=True).start()
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


def main():
    stop = threading.Event()
    threading.Thread(target=background_loop, args=(stop,), daemon=True).start()
    # 啟動時先檢查一次
    threading.Thread(target=check_all, daemon=True).start()
    threading.Timer(1.2, lambda: webbrowser.open(
        "http://localhost:%d" % PORT)).start()
    print("ReactCollect 補貨監控啟動：http://localhost:%d" % PORT)
    print("按 Ctrl+C 結束")
    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


if __name__ == "__main__":
    main()
