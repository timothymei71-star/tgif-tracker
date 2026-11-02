#!/usr/bin/env python3
"""Download each holding's new SEC filings (8-K, 6-K, 10-Q, ...) with an excerpt of the text.

Runs on GitHub Actions (the Claude sandbox cannot reach sec.gov). Writes
filings/<ET date>-<morning|recap>.json. The Claude tasks read that file so earnings and other
company news can quote real numbers from the filing instead of relying on a news search.

Usage: python scripts/fetch_filings.py morning|recap [--force] [--only-if-et-hour N]
"""
import argparse, html, json, re, sys, time, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ET = ZoneInfo("America/New_York")
TICKERS = ["BABA", "CRCL", "ETHA", "FUTU", "NVDA", "TIGR", "TSLA", "GOOG", "AVGO"]
FORMS = {"8-K", "8-K/A", "6-K", "6-K/A", "10-Q", "10-K", "20-F", "40-F", "S-1", "S-1/A", "F-1",
         "424B5", "424B2", "SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A", "SD", "DEF 14A", "DEFA14A"}
UA = {"User-Agent": "tgif-tracker (https://github.com/timothymei71-star/tgif-tracker)",
      "Accept-Encoding": "gzip, deflate"}
EXCERPT_CHARS = 4000


def get(url, **kw):
    time.sleep(0.15)  # SEC allows about 10 requests per second
    r = requests.get(url, headers=UA, timeout=30, **kw)
    r.raise_for_status()
    return r


def to_text(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def cik_map():
    data = get("https://www.sec.gov/files/company_tickers.json").json()
    return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}


def exhibit_url(cik, acc_nodash):
    """Press-release exhibit (EX-99.x) of a filing, if there is one."""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
    try:
        items = get(base + "index.json").json()["directory"]["item"]
    except Exception:
        return None
    for it in items:
        n = it["name"].lower()
        if re.search(r"(ex[-_]?99|exhibit99)", n) and n.endswith((".htm", ".html", ".txt")):
            return base + it["name"]
    return None


def filings_for(ticker, cik, since):
    sub = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    rec = sub["filings"]["recent"]
    out = []
    for i, form in enumerate(rec["form"]):
        if form not in FORMS:
            continue
        accepted = dt.datetime.fromisoformat(rec["acceptanceDateTime"][i].replace("Z", "+00:00"))
        if accepted < since:
            continue
        acc = rec["accessionNumber"][i]
        nodash = acc.replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/"
        item = {
            "form": form,
            "filed": rec["filingDate"][i],
            "acceptedET": accepted.astimezone(ET).strftime("%Y-%m-%d %-I:%M %p ET"),
            "items": rec["items"][i] if "items" in rec else "",
            "description": rec["primaryDocDescription"][i] if "primaryDocDescription" in rec else "",
            "url": base + rec["primaryDocument"][i],
            "indexUrl": f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{acc}-index.htm",
        }
        # Earnings and other news live in the press-release exhibit; for 6-Ks the main document is it.
        src = None
        if form.startswith(("8-K", "6-K")):
            ex = exhibit_url(cik, nodash)
            if ex:
                item["exhibitUrl"] = ex
            src = ex or item["url"]
        try:
            if src:
                item["excerpt"] = to_text(get(src).text)[:EXCERPT_CHARS]
        except Exception as e:
            item["excerptError"] = str(e)[:120]
        out.append(item)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["morning", "recap"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-if-et-hour", type=int)  # accepted so the workflow can pass the same args
    a = ap.parse_args()
    now = dt.datetime.now(ET)
    path = Path("filings") / f"{now.date().isoformat()}-{a.mode}.json"

    if a.only_if_et_hour is not None and not a.force:
        minutes = now.hour * 60 + now.minute
        lo, hi = (8 * 60, 12 * 60) if a.mode == "morning" else (16 * 60 + 10, 23 * 60 + 59)
        if not lo <= minutes <= hi:
            print(f"ET time {now:%H:%M} outside the {a.mode} window; skipping")
            return 0
        if path.exists():
            try:
                if not json.loads(path.read_text()).get("errors"):
                    print(f"{path} already exists with no errors; nothing to do")
                    return 0
            except Exception:
                pass

    # Look back 30 hours; on Monday go back to Friday afternoon so weekend filings are included.
    hours = 78 if now.weekday() == 0 else 30
    since = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=hours)
    errors, result = [], {}
    try:
        ciks = cik_map()
    except Exception as e:
        print(f"could not load the SEC ticker list: {e}", file=sys.stderr)
        return 1
    for t in TICKERS:
        cik = ciks.get(t)
        if not cik:
            errors.append(f"{t}: not found in the SEC ticker list")
            continue
        try:
            result[t] = filings_for(t, cik, since)
        except Exception as e:
            errors.append(f"{t}: {e}")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "mode": a.mode, "reportDate": now.date().isoformat(),
        "generatedAt": now.isoformat(timespec="seconds"), "lookbackHours": hours,
        "source": "SEC EDGAR", "filings": result, "errors": errors}, indent=1))
    n = sum(len(v) for v in result.values())
    print(f"wrote {path}: {n} filings, {len(errors)} errors")
    for e in errors:
        print("  ", e)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
