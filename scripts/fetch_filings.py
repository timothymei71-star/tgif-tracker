#!/usr/bin/env python3
"""Download each holding's new SEC filings (8-K, 6-K, 10-Q, ...) with an excerpt of the text.

Runs on GitHub Actions (the Claude sandbox cannot reach sec.gov). Writes
filings/<ET date>-<morning|recap>.json. The Claude tasks read that file so earnings and other
company news can quote real numbers from the filing instead of relying on a news search.

Usage: python scripts/fetch_filings.py morning|recap [--force] [--only-if-et-hour N]
"""
import argparse, html, json, os, re, sys, time, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ET = ZoneInfo("America/New_York")
TICKERS = ["BABA", "CRCL", "ETHA", "FUTU", "NVDA", "TIGR", "TSLA", "GOOG", "AVGO"]
FORMS = {"8-K", "8-K/A", "6-K", "6-K/A", "10-Q", "10-K", "20-F", "40-F", "S-1", "S-1/A", "F-1",
         "424B5", "424B2", "SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A", "SD", "DEF 14A", "DEFA14A"}
# The SEC requires real contact details in the User-Agent. Set the SEC_CONTACT secret in GitHub
# (for example "Jane Doe jane@example.com"); it is never written into the repo.
CONTACT = os.environ.get("SEC_CONTACT", "").strip() or "timothymei71-star@users.noreply.github.com"
UA = {"User-Agent": f"TGIF Tracker {CONTACT}",
      "Accept-Encoding": "gzip, deflate", "Accept": "application/json, text/html, */*"}
# Known SEC CIKs so the run does not depend on the www.sec.gov ticker list (checked via the entity name in the output).
KNOWN_CIKS = {"GOOG": 1652044, "NVDA": 1045810, "TSLA": 1318605, "AVGO": 1730168,
              "BABA": 1577552, "CRCL": 1876042, "FUTU": 1754581}  # TIGR and ETHA come from the SEC ticker list
EXCERPT_CHARS = 4000


def get(url, **kw):
    time.sleep(0.15)  # SEC allows about 10 requests per second
    r = requests.get(url, headers=UA, timeout=30, **kw)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code} from {url.split('//')[1].split('/')[0]}: {r.text[:120]!r}")
    return r


def to_text(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def cik_map():
    data = get("https://www.sec.gov/files/company_tickers.json").json()
    return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}


def exhibit_urls(cik, acc_nodash, acc):
    """All press-release exhibits (EX-99.x) of a filing. Returns (urls, note)."""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
    names, note = [], ""
    try:
        names = [it["name"] for it in get(base + "index.json").json()["directory"]["item"]]
    except Exception as e:
        note = f"index.json: {str(e)[:80]}"
        try:  # fall back to the human-readable index page
            page = get(f"{base}{acc}-index.htm").text
            names = [m.rsplit("/", 1)[-1] for m in re.findall(r'href="([^"]+)"', page)]
            note = ""
        except Exception as e2:
            note += f"; index page: {str(e2)[:80]}"
    urls = [base + n for n in names
            if re.search(r"(ex[-_]?99|exhibit[-_]?99)", n.lower()) and n.lower().endswith((".htm", ".html", ".txt"))]
    return urls, note


_names = {}


def entity_name(cik):
    return _names.get(cik, "")


TEXT_DIR = Path("filings") / "text"
MAX_SAVED_CHARS = 250_000


def save_text(day, ticker, form, nodash, n, text):
    d = TEXT_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{ticker}-{form.replace('/', '')}-{nodash}-{n}.txt"
    f.write_text(text[:MAX_SAVED_CHARS], encoding="utf-8")
    return str(f)


def filings_for(ticker, cik, since, day):
    sub = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    _names[cik] = sub.get("name", "")
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
        # Earnings and other news live in the press-release exhibits; for 6-Ks the main document is it.
        # The full text is saved in the repo so Claude can read it without reaching sec.gov (which it cannot).
        if form.startswith(("8-K", "6-K")):
            exs, note = exhibit_urls(cik, nodash, acc)
            if note:
                item["exhibitNote"] = note
            if exs:
                item["exhibitUrls"] = exs
            sources = exs or [item["url"]]
            item["textFiles"], texts = [], []
            for n, src in enumerate(sources[:4]):
                try:
                    text = to_text(get(src).text)
                    item["textFiles"].append(save_text(day, ticker, form, nodash, n, text))
                    texts.append(text)
                except Exception as e:
                    item.setdefault("textErrors", []).append(f"{src.rsplit('/', 1)[-1]}: {str(e)[:100]}")
            if texts:
                item["excerpt"] = texts[0][:EXCERPT_CHARS]
                item["textChars"] = sum(len(t) for t in texts)
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
        lo, hi = (6 * 60 + 30, 12 * 60) if a.mode == "morning" else (16 * 60 + 10, 23 * 60 + 59)
        if not lo <= minutes <= hi:
            print(f"ET time {now:%H:%M} outside the {a.mode} window; skipping")
            return 0
        if path.exists():
            try:
                prior = json.loads(path.read_text())
                if not prior.get("errors") and prior.get("final"):
                    print(f"{path} is already final with no errors; nothing to do")
                    return 0
            except Exception:
                pass

    # Look back 30 hours; on Monday go back to Friday afternoon so weekend filings are included.
    hours = 78 if now.weekday() == 0 else 30
    since = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=hours)
    errors, result, entities = [], {}, {}
    ciks = dict(KNOWN_CIKS)
    if any(t not in ciks for t in TICKERS):
        try:
            ciks = {**cik_map(), **ciks}
        except Exception as e:
            errors.append(f"SEC ticker list: {e}")
    for t in TICKERS:
        cik = ciks.get(t)
        if not cik:
            errors.append(f"{t}: not found in the SEC ticker list")
            continue
        try:
            result[t] = filings_for(t, cik, since, now.date().isoformat())
            entities[t] = entity_name(cik)
            for x in result[t]:
                for msg in x.get("textErrors", []):
                    errors.append(f"{t} {x['form']} text: {msg}")
        except Exception as e:
            errors.append(f"{t}: {e}")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "mode": a.mode, "reportDate": now.date().isoformat(),
        "generatedAt": now.isoformat(timespec="seconds"), "lookbackHours": hours,
        # "final" means this snapshot was taken just before the Claude task runs, so it includes
        # earnings released after the close (recap) or before 8 AM (morning).
        "final": now.hour * 60 + now.minute >= (8 * 60 if a.mode == "morning" else 17 * 60 + 25),
        "source": "SEC EDGAR", "entities": entities, "filings": result, "errors": errors}, indent=1))
    n = sum(len(v) for v in result.values())
    print(f"wrote {path}: {n} filings, {len(errors)} errors")
    for e in errors:
        print("  ", e)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
