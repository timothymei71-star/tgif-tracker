#!/usr/bin/env python3
"""Collect the day's headlines, official releases and analyst actions for the holdings.

Runs on GitHub Actions (the Claude sandbox blocks most of these sites). It only reads feeds that
publishers offer for automated use (RSS) plus public government feeds and Yahoo's analyst table.
It never reads article bodies, so every news item here is a headline plus the publisher's own
short summary. Writes news/<ET date>-<morning|recap>.json for the Claude tasks.

Usage: python scripts/fetch_news.py morning|recap [--force] [--only-if-et-hour N]
Optional env: BLS_CONTACT (contact string for the BLS User-Agent; BLS asks for one).
"""
import argparse, email.utils, html, json, os, re, sys, xml.etree.ElementTree as ET_, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ET = ZoneInfo("America/New_York")
BROWSER_UA = "Mozilla/5.0 (compatible; tgif-tracker/1.0; +https://github.com/timothymei71-star/tgif-tracker)"

# (source name, tier, url). Tier 2 = established press (headline + publisher summary only).
NEWS_FEEDS = [
    ("WSJ Markets", 2, "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"),
    ("WSJ Technology", 2, "https://feeds.content.dowjones.io/public/rss/RSSWSJD"),
    ("WSJ Business", 2, "https://feeds.content.dowjones.io/public/rss/WSJcomUSBusiness"),
    ("MarketWatch", 2, "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("MarketWatch Real-time", 2, "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("Bloomberg Markets", 2, "https://feeds.bloomberg.com/markets/news.rss"),
    ("Bloomberg Technology", 2, "https://feeds.bloomberg.com/technology/news.rss"),
    ("Financial Times", 2, "https://www.ft.com/rss/home"),
    ("Nikkei Asia", 2, "https://asia.nikkei.com/rss/feed/nar"),
    ("South China Morning Post (Business)", 2, "https://www.scmp.com/rss/92/feed"),
    ("South China Morning Post (China economy)", 2, "https://www.scmp.com/rss/91/feed"),
    ("CoinDesk", 2, "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", 2, "https://www.theblock.co/rss.xml"),
]
# Tier 1 government feeds.
OFFICIAL_FEEDS = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("BLS", "https://www.bls.gov/feed/bls_latest.rss"),
    ("BEA", "https://apps.bea.gov/rss/rss.xml"),
]
TICKER_WORDS = {
    "BABA": r"alibaba|\bbaba\b|taobao|tmall|alipay|ant group|\bqwen\b",
    "CRCL": r"circle internet|\bcrcl\b|\busdc\b|circle's|circle (?:ceo|stock|shares|stablecoin)",
    "ETHA": r"ethereum|\bether\b|\betha\b|ether etf",
    "FUTU": r"\bfutu\b|moomoo",
    "NVDA": r"nvidia|\bnvda\b|jensen huang",
    "TIGR": r"up fintech|tiger brokers|\btigr\b",
    "TSLA": r"tesla|\btsla\b|cybertruck|robotaxi|\boptimus\b",
    "GOOG": r"alphabet|google|waymo|youtube|\bgemini\b|\bgoog(?:l)?\b",
    "AVGO": r"broadcom|\bavgo\b",
}
MARKET_WORDS = r"stocks?|wall street|s&p 500|nasdaq|dow\b|treasur|yield|fed\b|federal reserve|inflation|jobs report|payrolls|gdp|oil|futures|selloff|rally|chip|semiconductor|china|hong kong|bitcoin|crypto"
TICKERS = list(TICKER_WORDS)


def parse_time(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except Exception:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def clean(s, n=400):
    s = re.sub(r"(?is)<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def fetch_feed(url, ua=BROWSER_UA):
    r = requests.get(url, headers={"User-Agent": ua, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}")
    root = ET_.fromstring(r.content)
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        f = {c.tag.split("}")[-1]: c for c in it}
        link = ""
        if "link" in f:
            link = (f["link"].text or f["link"].attrib.get("href") or "").strip()
        title = clean(f["title"].text if "title" in f else "", 300)
        def txt(*names):  # note: an XML element with no children is falsy, so never use `or` on elements
            for k in names:
                if k in f and f[k].text:
                    return f[k].text
            return ""
        summ = clean(txt("description", "summary", "content"))
        when = parse_time(txt("pubDate", "published", "updated", "date"))
        if title and link:
            out.append({"title": title, "summary": summ, "url": link, "published": when})
    if not out:
        raise RuntimeError("no items in feed")
    return out


HKEX_BASE = "https://www1.hkexnews.hk"
HKEX_COMPANIES = [("BABA", "9988", "Alibaba Group (HKEX 9988)")]  # only BABA is also listed in Hong Kong


def hkex_announcements(code, label, since):
    """Company announcements from HKEXnews (Tier 1). Returned in the same shape as the other official feeds."""
    h = {"User-Agent": BROWSER_UA, "Referer": HKEX_BASE + "/"}
    r = requests.get(f"{HKEX_BASE}/search/prefix.do", params={"callback": "cb", "lang": "EN", "type": "A", "name": code, "market": "SEHK"}, headers=h, timeout=30)
    if not r.ok:
        raise RuntimeError(f"HKEX lookup HTTP {r.status_code}")
    m = re.search(r"\((\{.*\})\)", r.text, re.S)
    info = json.loads(m.group(1)).get("stockInfo", []) if m else []
    stock = next((x for x in info if str(x.get("code")) == code), None)
    if not stock:
        raise RuntimeError("HKEX stock id not found")
    today = dt.datetime.now(ET).date()
    params = {"sortDir": 0, "sortByOptions": "DateTime", "category": 0, "market": "SEHK", "stockId": stock["stockId"],
              "documentType": -1, "fromDate": since.astimezone(ET).strftime("%Y%m%d"), "toDate": today.strftime("%Y%m%d"),
              "title": "", "searchType": 0, "t1code": -2, "t2Gcode": -2, "t2code": -2, "rowRange": 50, "lang": "EN"}
    r = requests.get(f"{HKEX_BASE}/search/titleSearchServlet.do", params=params, headers=h, timeout=30)
    if not r.ok:
        raise RuntimeError(f"HKEX search HTTP {r.status_code}")
    rows = r.json().get("result") or "[]"
    rows = json.loads(rows) if isinstance(rows, str) else rows
    out = []
    for x in rows:
        title = clean(x.get("TITLE", ""), 300)
        link = x.get("FILE_LINK", "")
        if title and link:
            out.append({"title": title, "summary": clean(x.get("LONG_TEXT", ""), 200),
                        "url": link if link.startswith("http") else HKEX_BASE + link,
                        "published": x.get("DATE_TIME")})
    return {"source": label, "tier": 1, "items": out[:25]}


def window_start(now):
    """Start of the report window: the previous weekday's 4:00 PM ET close."""
    d = now.date() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return dt.datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET)


def money(v):
    if v is None:
        return None
    return f"${v:,.0f}" if float(v) == int(v) else f"${v:,.2f}"


def analyst_rows(start, now):
    """Analyst actions inside the report window, de-duplicated, with one digest line per stock per day.

    Yahoo sometimes gives a real time and sometimes only a date. With a time, the action must fall
    between the previous close and now. With only a date, it counts when that date is after the
    previous close's date, because an action dated on the close day belongs to the previous report.
    """
    import yfinance as yf
    res, errs = {}, []
    for t in TICKERS:
        try:
            df = yf.Ticker(t).upgrades_downgrades
            seen, actions = {}, []
            if df is not None and len(df):
                for idx, r in df.iterrows():
                    ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else None
                    if ts is None:
                        continue
                    has_time = (ts.hour, ts.minute, ts.second) != (0, 0, 0)
                    if has_time:
                        ts = (ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)).astimezone(ET)
                        if not start <= ts <= now:
                            continue
                        day = ts.date()
                    else:
                        day = ts.date()
                        if not start.date() < day <= now.date():
                            continue
                    g = lambda k: (None if k not in r or r[k] != r[k] else r[k])
                    row = {"date": day.isoformat(), "time": ts.strftime("%-I:%M %p ET") if has_time else None,
                           "firm": g("Firm"), "action": g("Action"), "fromRating": g("FromGrade"), "toRating": g("ToGrade"),
                           "targetAction": g("priceTargetAction"), "oldTarget": g("priorPriceTarget"), "newTarget": g("currentPriceTarget")}
                    key = (row["date"], row["firm"], row["fromRating"], row["toRating"], row["oldTarget"], row["newTarget"])
                    if key in seen:
                        seen[key]["repeats"] += 1  # same call listed more than once
                        continue
                    row["repeats"] = 1
                    seen[key] = row
                    actions.append(row)
            digest = []
            for day in sorted({x["date"] for x in actions}, reverse=True):
                rows = sorted((x for x in actions if x["date"] == day), key=lambda x: x["firm"] or "")
                parts = []
                for x in rows:
                    bits = []
                    if x["fromRating"] and x["toRating"] and x["fromRating"] != x["toRating"]:
                        bits.append(f'{x["fromRating"]} → {x["toRating"]}')
                    elif x["toRating"]:
                        bits.append(f'{x["toRating"]} (unchanged)')
                    if x["oldTarget"] and x["newTarget"] and x["oldTarget"] != x["newTarget"]:
                        bits.append(f'target {money(x["oldTarget"])} → {money(x["newTarget"])}')
                    elif x["newTarget"]:
                        bits.append(f'target {money(x["newTarget"])} (unchanged)')
                    parts.append(f'{x["firm"]}: ' + ", ".join(bits))
                moved = [(x["newTarget"] or 0) - (x["oldTarget"] or 0) for x in rows if x["oldTarget"] and x["newTarget"]]
                if moved and all(m < 0 for m in moved) and len(moved) == len(rows):
                    label = f"{len(rows)} price target cut{'s' if len(rows) > 1 else ''}"
                elif moved and all(m > 0 for m in moved) and len(moved) == len(rows):
                    label = f"{len(rows)} price target raise{'s' if len(rows) > 1 else ''}"
                else:
                    label = f"{len(rows)} analyst action{'s' if len(rows) > 1 else ''}"
                digest.append({"date": day, "count": len(rows), "firms": [x["firm"] for x in rows],
                               "line": f"{label}: " + "; ".join(parts)})
            res[t] = {"actions": actions, "digest": digest}
        except Exception as e:
            errs.append(f"{t} analysts: {str(e)[:100]}")
    return res, errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["morning", "recap"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-if-et-hour", type=int)
    a = ap.parse_args()
    now = dt.datetime.now(ET)
    path = Path("news") / f"{now.date().isoformat()}-{a.mode}.json"

    if a.only_if_et_hour is not None and not a.force:
        minutes = now.hour * 60 + now.minute
        lo, hi = (6 * 60 + 30, 12 * 60) if a.mode == "morning" else (16 * 60 + 15, 23 * 60 + 59)
        if not lo <= minutes <= hi:
            print(f"ET time {now:%H:%M} outside the {a.mode} window; skipping")
            return 0
        if path.exists():
            try:
                prior = json.loads(path.read_text())
                if prior.get("complete") and prior.get("final"):
                    print(f"{path} already complete and final; nothing to do")
                    return 0
            except Exception:
                pass

    hours = 78 if now.weekday() == 0 else 30
    since = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=hours)
    errors, ok_feeds = [], 0

    feeds, seen = [], set()
    for name, tier, url in NEWS_FEEDS:
        try:
            items = fetch_feed(url)
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")
            continue
        ok_feeds += 1
        keep = []
        for it in items:
            if it["published"] and it["published"] < since:
                continue
            text = f'{it["title"]} {it["summary"]}'.lower()
            tags = [t for t, pat in TICKER_WORDS.items() if re.search(pat, text)]
            market = bool(re.search(MARKET_WORDS, text))
            if not tags and not market:
                continue
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            keep.append({"title": it["title"], "summary": it["summary"], "url": it["url"],
                         "published": it["published"].astimezone(ET).strftime("%Y-%m-%d %-I:%M %p ET") if it["published"] else None,
                         "tickers": tags, "marketWide": market and not tags})
        feeds.append({"source": name, "tier": tier, "items": keep[:60]})

    contact = os.environ.get("BLS_CONTACT", "").strip()
    official = []
    for name, url in OFFICIAL_FEEDS:
        ua = f"TGIF Tracker {contact}" if (name == "BLS" and contact) else BROWSER_UA
        try:
            items = fetch_feed(url, ua)
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")
            continue
        official.append({"source": name, "tier": 1, "items": [
            {"title": i["title"], "summary": i["summary"], "url": i["url"],
             "published": i["published"].astimezone(ET).strftime("%Y-%m-%d %-I:%M %p ET") if i["published"] else None}
            for i in items if not i["published"] or i["published"] >= since][:25]})

    for t, code, label in HKEX_COMPANIES:
        try:
            official.append(hkex_announcements(code, label, since))
        except Exception as e:
            errors.append(f"HKEX {t}: {str(e)[:100]}")

    analysts, aerrs = analyst_rows(window_start(now), now)
    errors += aerrs

    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "mode": a.mode, "reportDate": now.date().isoformat(), "generatedAt": now.isoformat(timespec="seconds"),
        "lookbackHours": hours,
        "note": "News items are feed headlines plus the publisher's own short summary only; article bodies were not read. Analyst data is from Yahoo Finance.",
        "complete": ok_feeds >= 3 and not aerrs,
        "final": now.hour * 60 + now.minute >= (8 * 60 if a.mode == "morning" else 17 * 60 + 25),
        "windowStart": window_start(now).isoformat(timespec="minutes"),
        "news": feeds, "official": official, "analysts": analysts, "errors": errors}, indent=1))
    n = sum(len(f["items"]) for f in feeds)
    print(f"wrote {path}: {ok_feeds}/{len(NEWS_FEEDS)} feeds, {n} items, {sum(len(v['actions']) for v in analysts.values())} analyst actions, {len(errors)} errors")
    for e in errors:
        print("  ", e)
    return 0 if ok_feeds else 1


if __name__ == "__main__":
    sys.exit(main())
