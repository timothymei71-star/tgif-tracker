#!/usr/bin/env python3
"""Fetch all numeric market data for the TGIF tracker and write prices/<date>-<mode>.json.

Modes:
  recap   - closes for the day just ended, index closes, 10Y yield, BTC/ETH at 4:00 PM ET
  morning - premarket price at 8:00 AM ET, previous closes, 10Y, BTC/ETH at 8:00 AM ET

Only numbers come from here. Nothing is estimated: if a value can't be fetched it is
left out and an entry is added to "errors".
Usage: python scripts/fetch_prices.py recap|morning [--only-if-et-hour N] [--force]
"""
import argparse, csv, io, json, sys, warnings, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import yfinance as yf

warnings.filterwarnings("ignore", message=".*inplace keyword.*")  # noisy yfinance/pandas deprecation notice
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
TICKERS = ["BABA", "CRCL", "ETHA", "FUTU", "NVDA", "TIGR", "TSLA", "GOOG", "AVGO"]
INDICES = [("Golden Dragon (China)", "^HXC"), ("S&P 500", "^GSPC"), ("Nasdaq Composite", "^IXIC"), ("SOX (semis)", "^SOX")]
CRYPTO = [("Bitcoin (BTC)", "BTC-USD"), ("Ethereum (ETH)", "ETH-USD")]
HEADERS = {"User-Agent": "tgif-tracker/1.0"}


def pct(new, old):
    return round((new / old - 1) * 100, 2) if old else None


def _bars(h):
    return [(i.date(), float(r["Close"])) for i, r in h.iterrows() if r["Close"] == r["Close"]]


def daily(sym):
    """Daily bars as a list of (date, close), oldest first.

    Uses explicit ET dates rather than period="15d": a period query can drop today's bar when it is
    run late in the evening (after midnight UTC). If today's bar is still missing after the close,
    retry with other ranges before giving up.
    """
    today = dt.datetime.now(ET).date()
    end = today + dt.timedelta(days=1)
    t = yf.Ticker(sym)
    bars = _bars(t.history(start=(end - dt.timedelta(days=25)).isoformat(), end=end.isoformat(),
                           interval="1d", auto_adjust=False))
    if (not bars or bars[-1][0] != today) and dt.datetime.now(ET).hour >= 16:
        for kw in ({"period": "1mo"}, {"period": "5d"}):
            retry = _bars(t.history(interval="1d", auto_adjust=False, **kw))
            if retry and retry[-1][0] == today:
                return retry
    return bars


def quote_close(sym, today):
    bars = daily(sym)
    if not bars or bars[-1][0] != today:
        raise ValueError(f"no bar for {today} (last: {bars[-1][0] if bars else None})")
    if len(bars) < 2:
        raise ValueError("need two daily bars")
    return {"close": round(bars[-1][1], 2), "prevClose": round(bars[-2][1], 2),
            "changePct": pct(bars[-1][1], bars[-2][1])}


def fred_series(series_id):
    """Daily closes from FRED's public CSV (no key). Used as a fallback for the Golden Dragon index."""
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id},
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        v = row.get(series_id, ".")
        if v not in (".", ""):
            out.append((dt.date.fromisoformat(row["observation_date" if "observation_date" in row else "DATE"]), float(v)))
    return sorted(out)


def premarket(sym, today, cutoff):
    prev = [b for b in daily(sym) if b[0] < today]
    if not prev:
        raise ValueError("no previous close")
    h = yf.Ticker(sym).history(period="2d", interval="1m", prepost=True, auto_adjust=False)
    h = h[(h.index.date == today) & (h.index <= cutoff)]
    out = {"prevClose": round(prev[-1][1], 2)}
    if len(h):
        p = float(h["Close"].iloc[-1])
        out.update({"premarket": round(p, 2), "premarketChangePct": pct(p, prev[-1][1]),
                    "premarketAsOf": h.index[-1].astimezone(ET).strftime("%-I:%M %p ET")})
    return out


def coinbase_price(product, at_et):
    """Close of the 1-minute candle that ends at `at_et` (so 4:00 PM ET = the 3:59 candle)."""
    start = (at_et - dt.timedelta(minutes=1)).astimezone(UTC)
    end = start + dt.timedelta(seconds=59)
    r = requests.get(f"https://api.exchange.coinbase.com/products/{product}/candles",
                     params={"granularity": 60, "start": start.isoformat(), "end": end.isoformat()},
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise ValueError("no candle returned")
    return float(rows[0][4])  # [time, low, high, open, close, volume]


def treasury_10y(today):
    y = today.year
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           f"daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve"
           f"&field_tdr_date_value={y}&page&_format=csv")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    parsed = [(dt.datetime.strptime(x["Date"], "%m/%d/%Y").date(), float(x["10 Yr"])) for x in rows if x.get("10 Yr")]
    parsed.sort()
    return parsed


def ten_year(today, require_today):
    try:
        rows = treasury_10y(today)
        use = [r for r in rows if r[0] <= today]
        if require_today and (not use or use[-1][0] != today):
            raise ValueError("Treasury has not published today's yield yet")
        if len(use) >= 2:
            return {"value": f"{use[-1][1]:.2f}%", "changeBp": round((use[-1][1] - use[-2][1]) * 100),
                    "asOfDate": use[-1][0].isoformat(), "source": "US Treasury daily par yield curve"}
    except Exception as e:  # fall back to Yahoo ^TNX (quoted in percent)
        err = str(e)
    bars = [b for b in daily("^TNX") if b[0] <= today]
    if len(bars) < 2:
        raise ValueError(f"10Y unavailable ({err})")
    return {"value": f"{bars[-1][1]:.2f}%", "changeBp": round((bars[-1][1] - bars[-2][1]) * 100),
            "asOfDate": bars[-1][0].isoformat(), "source": "Yahoo Finance ^TNX (Treasury not available)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["recap", "morning"])
    ap.add_argument("--only-if-et-hour", type=int, help="exit quietly unless the current ET hour matches (handles DST)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    now = dt.datetime.now(ET)
    if a.only_if_et_hour is not None and not a.force and now.hour != a.only_if_et_hour:
        print(f"ET hour is {now.hour}, wanted {a.only_if_et_hour}; skipping")
        return 0
    today = now.date()
    if today.weekday() >= 5 and not a.force:
        print("Weekend; skipping")
        return 0

    errors, out = [], {"mode": a.mode, "reportDate": today.isoformat(),
                       "generatedAt": now.strftime("%Y-%m-%d %H:%M ET")}
    cutoff = now.replace(hour=8, minute=0, second=0, microsecond=0)
    when = now.replace(hour=16, minute=0, second=0, microsecond=0) if a.mode == "recap" else cutoff

    tick = {}
    for s in TICKERS:
        try:
            tick[s] = quote_close(s, today) if a.mode == "recap" else premarket(s, today, cutoff)
        except Exception as e:
            errors.append(f"{s}: {e}")
    out["tickers"] = tick

    def index_quote(sym):
        if a.mode == "recap":
            return quote_close(sym, today)
        bars = [b for b in daily(sym) if b[0] < today]
        return {"close": round(bars[-1][1], 2), "changePct": pct(bars[-1][1], bars[-2][1])}

    def index_quote_fred(series_id):
        bars = [b for b in fred_series(series_id) if (b[0] == today if a.mode == "recap" else b[0] < today)]
        if len(bars) < 2 and a.mode != "recap":
            raise ValueError("not enough FRED observations")
        if a.mode == "recap":
            allb = [b for b in fred_series(series_id) if b[0] <= today]
            if not allb or allb[-1][0] != today or len(allb) < 2:
                raise ValueError("FRED has no value for today yet")
            return {"close": round(allb[-1][1], 2), "changePct": pct(allb[-1][1], allb[-2][1])}
        return {"close": round(bars[-1][1], 2), "changePct": pct(bars[-1][1], bars[-2][1])}

    idx = []
    for name, sym in INDICES:
        try:
            try:
                q = index_quote(sym)
            except Exception as e1:
                if sym != "^HXC":
                    raise
                try:
                    q = index_quote_fred("NASDAQHXC")  # Golden Dragon fallback
                except Exception as e2:
                    raise ValueError(f"Yahoo failed ({e1}); FRED failed ({e2})")
                errors.append(f"{name}: Yahoo failed ({e1}); used FRED instead")
            idx.append({"name": name, "value": f"{q['close']:,.2f}", "changePct": q["changePct"]})
        except Exception as e:
            errors.append(f"{name}: {e}")
    out["indices"] = idx

    try:
        out["tenYear"] = ten_year(today, require_today=(a.mode == "recap"))
    except Exception as e:
        errors.append(f"10Y: {e}")

    cr = []
    for name, prod in CRYPTO:
        try:
            p = coinbase_price(prod, when)
            p0 = coinbase_price(prod, when - dt.timedelta(days=1))
            cr.append({"name": name, "price": f"${p:,.2f}", "changePct": pct(p, p0)})
        except Exception as e:
            errors.append(f"{name}: {e}")
    out["crypto"] = cr
    out["cryptoTime"] = f"{when.strftime('%-I:%M %p')} ET prices (Coinbase)"
    out["errors"] = errors

    if a.mode == "recap" and not tick:
        print("No ticker data for today; not writing a file")
        print(json.dumps(errors, indent=1))
        closed = bool(errors) and all("no bar for" in e for e in errors)
        if closed:
            print("Every ticker reports no bar for today: market closed (holiday). Nothing to do.")
            return 0
        print("FAILED: data could not be fetched (not a market holiday). Failing the run so it shows red in Actions.")
        return 1

    path = Path("prices") / f"{today.isoformat()}-{a.mode}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path}; {len(tick)}/{len(TICKERS)} tickers, {len(errors)} errors")
    for e in errors:
        print("  ERROR", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
