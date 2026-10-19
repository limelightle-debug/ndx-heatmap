"""Fetch Nasdaq-100 heatmap data from finviz and write data/ndx.json.

Runs in GitHub Actions. Writes the file only when the data actually changed,
so runs outside US market hours do not create commits.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent.parent / "data" / "ndx.json"
RANKS = OUT.parent / "rank_history.json"
INDEX_DAILY = OUT.parent / "ndx_daily.json"
PERIODS = ["d1", "w1", "w4", "w13", "w26", "ytd", "w52"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finviz.com/map?t=sec_ndx",
}

session = requests.Session()
session.headers.update(HEADERS)


def get(url):
    last = None
    for attempt in range(3):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


NASDAQ_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


def num(x):
    return float(str(x).replace("$", "").replace(",", "").strip())


def regular_session(stamp):
    """True for an official close ("Oct 16, 2026") or a value stamped 9:30-16:00 ET."""
    m = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AP]M)", stamp or "", re.I)
    if not m:
        return bool(stamp)
    t = (int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)) * 60 + int(m.group(2))
    return 9 * 60 + 30 <= t <= 16 * 60


def nasdaq_json(path, query=""):
    r = requests.get(f"https://api.nasdaq.com/api/quote/NDX/{path}?assetclass=index{query}",
                     headers=NASDAQ_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("data") or {}


def fetch_index():
    """The Nasdaq-100 index level from Nasdaq.com: price, previous close and the day's high and low."""
    info = nasdaq_json("info")
    p = None
    for key in ("primaryData", "secondaryData"):
        c = info.get(key) or {}
        if c.get("lastSalePrice") and regular_session(c.get("lastTradeTimestamp")):
            p = c
            break
    if p is None:
        return None
    price = num(p["lastSalePrice"])
    q = {"price": round(price, 2), "prev": round(price - num(p.get("netChange") or 0), 2),
         "time": p.get("lastTradeTimestamp")}
    try:
        summ = nasdaq_json("summary").get("summaryData") or {}
        print("index summary fields:", sorted(summ))
        vals = {k.lower(): str((v or {}).get("value", "")) for k, v in summ.items() if isinstance(v, dict)}
        for k, v in vals.items():
            if "high" in k and "low" in k and "/" in v and "52" not in k:
                hi, lo = (num(x) for x in v.split("/"))
                q.update(high=round(hi, 2), low=round(lo, 2))
        hi = next((v for k, v in vals.items() if k in ("todayshigh", "todayhigh", "dayhigh")), None)
        lo = next((v for k, v in vals.items() if k in ("todayslow", "todaylow", "daylow")), None)
        if hi and lo and "high" not in q:
            q.update(high=round(num(hi), 2), low=round(num(lo), 2))
        pc = vals.get("previousclose")
        if pc:
            q["prev"] = round(num(pc), 2)
    except (requests.RequestException, ValueError) as e:
        print(f"warning: index summary: {e}", file=sys.stderr)
    return q


def quote_day(stamp):
    """yyyymmdd of a Nasdaq timestamp such as "Oct 19, 2026 9:36 AM ET", or None."""
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", stamp or "")
    mon = "JanFebMarAprMayJunJulAugSepOctNovDec".find(m.group(1)) if m else -1
    return None if mon < 0 else int(m.group(3)) * 10000 + (mon // 3 + 1) * 100 + int(m.group(2))


def update_index_daily(index):
    """Daily open/high/low/close of the index in data/ndx_daily.json, for the candle chart.

    The official history comes from Nasdaq.com (about ten years, kept and extended run by run;
    fetched at most every 30 minutes). Today's bar is built from the live quote until the
    official row appears; its open is the first value seen today, so it is approximate."""
    store = json.loads(INDEX_DAILY.read_text(encoding="utf-8")) if INDEX_DAILY.exists() else {}
    rows = {r[0]: r[1:5] for r in store.get("daily", [])}
    now = datetime.now(timezone.utc)
    fetched = store.get("fetchedAt")
    if not rows or not fetched or (now - datetime.fromisoformat(fetched)).total_seconds() > 1800:
        today = datetime.now(ZoneInfo("America/New_York")).date()
        j = nasdaq_json("historical", f"&fromdate={today.replace(year=today.year - 10)}&todate={today}&limit=10000")
        got = 0
        for r in ((j.get("tradesTable") or {}).get("rows") or []):
            try:
                mo, d, y = r["date"].split("/")
                c = num(r["close"])
                o, h, l = (num(r[k]) if str(r.get(k, "")).strip() not in ("", "N/A") else c for k in ("open", "high", "low"))
                rows[int(f"{y}{mo}{d}")] = [round(o, 2), round(h, 2), round(l, 2), round(c, 2)]
                got += 1
            except (KeyError, ValueError):
                continue
        print(f"index history: {got} days from Nasdaq.com")
        if not got and not rows:
            raise RuntimeError(f"no index history rows; keys: {sorted(j)[:8]}")
        fetched = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    out = {"fetchedAt": fetched, "daily": [[d, *v] for d, v in sorted(rows.items())]}
    qd = quote_day((index or {}).get("time"))
    if qd and rows and qd > max(rows):
        before = store.get("today")
        o = before[1] if before and before[0] == qd else index["price"]
        hs = [x for x in (index.get("high"), index["price"]) if x]
        ls = [x for x in (index.get("low"), index["price"]) if x]
        out["today"] = [qd, o, max(hs), min(ls), index["price"]]
    if out != store:
        INDEX_DAILY.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")


def fetch_perf():
    perf = {}
    for p in PERIODS:
        j = get(f"https://finviz.com/api/map_perf?t=sec_ndx&st={p}").json()
        nodes = {k: round(float(v), 2) for k, v in j.get("nodes", {}).items()
                 if isinstance(v, (int, float))}
        if len(nodes) < 90:
            raise RuntimeError(f"perf {p}: only {len(nodes)} tickers")
        perf[p] = nodes
        time.sleep(0.5)
    return perf


def parse_cap(text):
    m = re.match(r"^([\d.]+)([TBMK])$", text.strip())
    if not m:
        return None
    v = float(m.group(1))
    mult = {"T": 1_000_000, "B": 1_000, "M": 1, "K": 0.001}[m.group(2)]
    return round(v * mult)  # millions of USD


def fetch_stocks():
    rows, total, start = [], None, 1
    while start < 400:
        html = get(f"https://finviz.com/screener.ashx?v=111&f=idx_ndx&r={start}").text
        soup = BeautifulSoup(html, "html.parser")
        if total is None:
            m = re.search(r"#\d+\s*/\s*(\d+)\s*Total", soup.get_text(" "))
            total = int(m.group(1)) if m else None
        table = soup.select_one("table.screener_table")
        if table is None:
            raise RuntimeError("screener table not found")
        head = [c.get_text(strip=True) for c in table.select("tr")[0].find_all(["th", "td"])]
        idx = {name: head.index(name) for name in ["Ticker", "Company", "Sector", "Industry", "Market Cap"]}
        page = []
        for tr in table.select("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < len(head):
                continue
            cell = tds[idx["Ticker"]]
            a = cell.select_one("a.tab-link")
            if a is not None:
                ticker = a.get_text(strip=True)
            else:  # fall back to the t= parameter of the quote link
                link = cell.find("a", href=re.compile(r"[?&]t="))
                m = re.search(r"[?&]t=([A-Z.\-]+)", link["href"]) if link else None
                ticker = m.group(1) if m else cell.get_text(strip=True)
            page.append({
                "t": ticker,
                "name": tds[idx["Company"]].get_text(strip=True),
                "sec": tds[idx["Sector"]].get_text(strip=True),
                "ind": tds[idx["Industry"]].get_text(strip=True),
                "cap": parse_cap(tds[idx["Market Cap"]].get_text(strip=True)),
            })
        if not page:
            break
        rows.extend(page)
        if total and len(rows) >= total:
            break
        start += 20
        time.sleep(1)
    # One company listed twice (GOOG/GOOGL) would be counted twice: keep one line per company.
    by_company = {}
    for s in rows:
        if not s["cap"]:
            continue
        cur = by_company.get(s["name"])
        if cur is None or len(s["t"]) > len(cur["t"]):
            by_company[s["name"]] = s
    stocks = sorted(by_company.values(), key=lambda s: -s["cap"])
    if len(stocks) < 90:
        raise RuntimeError(f"screener: only {len(stocks)} stocks")
    return stocks


QQQ_HOLDINGS = ("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/holdings/fund"
                "?idType=ticker&interval=monthly&productType=ETF")


def fetch_weights():
    """Index weights from the holdings of Invesco QQQ, which fully replicates the Nasdaq-100.

    GOOG and GOOGL are merged into one Alphabet line (GOOGL). Weights are rescaled to sum to 100
    over the stock holdings (futures and cash are left out).
    """
    r = session.get(QQQ_HOLDINGS, timeout=30, headers={
        "Origin": "https://www.invesco.com",
        "Referer": "https://www.invesco.com/qqq-etf/en/about.html",
        "Accept": "application/json",
    })
    r.raise_for_status()
    j = r.json()
    w, total = {}, 0.0
    for h in j.get("holdings", []):
        pct, ticker = h.get("percentageOfTotalNetAssets"), h.get("ticker")
        kind = h.get("securityTypeName") or ""
        if not ticker or not isinstance(pct, (int, float)):
            continue
        if "Common Stock" not in kind and "Depository Receipt" not in kind:
            continue
        t = "GOOGL" if ticker == "GOOG" else ticker
        w[t] = w.get(t, 0.0) + pct
        total += pct
    if len(w) < 90 or total <= 0:
        raise RuntimeError(f"QQQ holdings: only {len(w)} stocks")
    return {"asOf": j.get("effectiveDate"), "source": "Invesco QQQ",
            "w": {k: round(v / total * 100, 4) for k, v in w.items()}}


def next_month(key):
    y, m = map(int, key.split("-"))
    return f"{y + (m == 12)}-{1 if m == 12 else m + 1:02d}"


def update_rank_history(stocks):
    """Keep the market-cap rank of every current constituent for the current month (New York time).

    Each run overwrites the current month, so the last run of a month leaves the month-end rank.
    """
    if not RANKS.exists():
        return
    hist = json.loads(RANKS.read_text(encoding="utf-8"))
    months, ranks = hist["months"], hist["ranks"]
    cur = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m")
    if cur < months[-1]:
        return
    while months[-1] < cur:
        months.append(next_month(months[-1]))
        for t in ranks:
            ranks[t].append(None)
    live = {s["t"]: i + 1 for i, s in enumerate(sorted(stocks, key=lambda s: -s["cap"]))}
    for t in ranks:  # stocks that left the index get no rank for this month
        ranks[t][-1] = None
    for t, r in live.items():
        if t not in ranks:
            ranks[t] = [None] * len(months)
        ranks[t][-1] = r
    text = json.dumps(hist, ensure_ascii=False, separators=(",", ":"))
    if text != RANKS.read_text(encoding="utf-8"):
        RANKS.write_text(text, encoding="utf-8")
        print(f"rank history: {cur} updated")


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    perf = fetch_perf()
    try:
        weights = fetch_weights()
    except Exception as e:  # keep the last known weights if Invesco is unavailable
        print(f"warning: {e}; keeping previous weights", file=sys.stderr)
        weights = old.get("weights")
    try:
        stocks = fetch_stocks()
    except Exception as e:  # keep the last known list if the screener fails
        print(f"warning: {e}; keeping previous stock list", file=sys.stderr)
        stocks = old.get("stocks")
        if not stocks:
            raise
    try:
        index = fetch_index() or old.get("index")
    except Exception as e:  # the heatmap still updates without the index level
        print(f"warning: index: {e}", file=sys.stderr)
        index = old.get("index")
    try:
        update_index_daily(index)
    except Exception as e:  # the heatmap still updates without the index chart
        print(f"warning: index history: {e}", file=sys.stderr)
        if not INDEX_DAILY.exists() or "error" in json.loads(INDEX_DAILY.read_text(encoding="utf-8")):
            # leave the reason where it can be read without signing in
            INDEX_DAILY.write_text(json.dumps({"error": f"{type(e).__name__}: {e}"[:400], "daily": []}) + "\n", encoding="utf-8")
    try:
        update_rank_history(stocks)
    except Exception as e:  # the heatmap data still updates if this fails
        print(f"warning: rank history: {e}", file=sys.stderr)
    if (old.get("perf") == perf and old.get("stocks") == stocks and old.get("weights") == weights
            and old.get("index") == index):
        print("no change")
        return
    data = {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "finviz",
        "stocks": stocks,
        "perf": perf,
    }
    if weights:
        data["weights"] = weights
    if index:
        data["index"] = index
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"updated: {len(stocks)} stocks, NVDA d1 {perf['d1'].get('NVDA')}")


if __name__ == "__main__":
    main()
