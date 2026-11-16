# Shared rules for the Morning Brief and Daily Recap tasks

These rules are read by the scheduled Claude tasks. Change a rule here and the next run follows it.

Holdings (static list, do not change it): BABA, CRCL, ETHA, FUTU, NVDA, TIGR, TSLA, GOOG, AVGO. Keep the same names as the existing entries in data.json. All times are ET (America/New_York).

You write NEWS only. A separate script produces every number. Never edit index.html, rules/, or anything in scripts/, .github/, prices/, filings/ or news/.

## Numbers are not yours to write
- Closes, premarket prices, percent changes, index levels, the 10Y yield and BTC/ETH prices come from the price script and are shown on the site from prices/<date>-<mode>.json. Do not search for them. Leave these out of your section: tickers[].close, tickers[].changePct, tickers[].premarket, market.indices, market.crypto, market.cryptoTime, market.cryptoNote.
- Recap only: in the text of a story you may say how the stock closed (for example "closed up 3.5%"), copying the figure exactly from prices/<today>-recap.json. Never use a figure from anywhere else.

## Data already downloaded for you (read these before any web search)
Never try to open sec.gov, finance.yahoo.com or the feed sites yourself: they block Claude. Everything you need from them is already saved in the repo.

1. filings/<today>-<mode>.json: each holding's new SEC filings (8-K, 6-K, 10-Q, 10-K, 20-F and similar) with form, items, acceptedET, url. For 8-K and 6-K the full text of the press-release exhibits is saved in the repo at the paths in `textFiles`; read those files. Quote the key reported figures from them (revenue, earnings per share, guidance, and so on) for earnings and results, and cite the filing `url` as the source with sourceDepth "full". If `textErrors` or `exhibitNote` is present for a filing, say only what the filing's form and items tell you. Ignore routine filings (prospectus supplements, proxy materials, routine ownership forms) unless they matter to the price. Never write from memory about what a filing says.
2. news/<today>-<mode>.json:
   - `news`: headline plus the publisher's own short summary from Bloomberg, WSJ, MarketWatch, FT, Nikkei Asia, SCMP, CoinDesk and The Block (Tier 2). Each item has `tickers` and `marketWide`. Headline and summary only; the article body was not read.
   - `official`: Federal Reserve, BLS, BEA and (for BABA) HKEX releases (Tier 1). Use them for market.driver, the calendar and market.dataRelease.
   - `analysts`: per ticker, `actions` and `digest`. See "Analyst actions".
   - `errors`: feeds that failed. An empty list for a holding means nothing was found, not necessarily that nothing happened.
3. Both files have `final`. When it is false the snapshot was taken early and may miss late filings; the task's own file says how long to wait for a final one.
If a file is missing, carry on with web search under the rules below.

## Analyst actions
- The script already limits actions to this report's window and removes repeats. Do not add analyst actions that are not in the file, and do not repeat an action from a previous day's report.
- Make ONE item per ticker per date from `analysts[TICKER].digest`: type "analyst", headline = the digest label (for example "5 price target cuts on Circle"), summary = the digest `line`, and `changes` = a list with one entry per firm for that date taken from `actions` ({firm, oldRating, newRating, oldTarget, newTarget}; targets written like "$110"; leave out an old value that is missing). Same-day actions are one item, never one item each.
- sourceName "Yahoo Finance analyst data", sourceUrl https://finance.yahoo.com/quote/<TICKER>/analysis, pubTime the date. This is the only allowed use of Yahoo Finance.

## Sourcing rules (news only)
- Tier 1 (preferred): company press releases and newsrooms, SEC filings, HKEX announcements, the Federal Reserve, BLS and BEA. For BABA, FUTU and TIGR the earnings release is also a 6-K, which is in the filings file.
- Tier 2 (when no Tier 1 source covers the item): Reuters, Bloomberg, WSJ, CNBC, AP, MarketWatch, Barron's, Financial Times, Nikkei Asia and South China Morning Post. CoinDesk and The Block only for crypto-specific items. SCMP is owned by Alibaba, so for BABA never rely on SCMP alone; back it up with another source or leave the item out.
- Licensed reprints: a wire story (Reuters, Bloomberg, AP) republished by a news outlet that carries it under license and shows the wire credit is allowed. Always label it "Reuters via <outlet>" (or "Bloomberg via", "AP via"). Do not use copies from scrapers or aggregators, and do not relabel a reprint as if it came from the original site.
- NOT allowed: opinion pieces, forums, social media, blogs, reposts and aggregators (for example KuCoin, Stocktwits, TipRanks, Yahoo Finance except the analyst data above, Invezz, Investing Cube, GuruFocus, Motley Fool, Seeking Alpha, Benzinga, 24/7 Wall St). If a story only appears on one of these, find the original Tier 1 or Tier 2 source or a licensed reprint; if you can't, drop the item.
- How much you read. Every item has `sourceDepth`. "full" means you read the article or the saved filing text and wrote from what it says. "headline" means you only had the headline and the publisher's own summary or opening lines (from the news file, or visible on the page without logging in). A "headline" item restates only what that headline and summary say: no added numbers, causes, context or conclusions. Never write from search-engine snippets or a third-party repost.
- Never try to get around a paywall or a block (no archive sites, extensions, page-source tricks or alternate user agents). Some sites (for example CNBC and AP) block Claude; do not work around that. Use the feed items, another allowed source, or drop the item.
- Every sourceUrl must be a real URL from the downloaded files or one you retrieved this run. Never invent or guess a link.
- Add a top-level "droppedLinks" list to your section: {source, headline, url, reason} for every article you could not use because it could not be opened and had no usable headline summary. Use [] if none.

## Content rules
- A ticker is "updated" only for company-specific news: its own earnings or results, guidance, analyst rating or target changes, regulatory or legal news, deals or corporate actions. A sector or market-wide move (a chip selloff, a rates move, a Fed decision) is not a ticker item; put it in market.driver.
- A ticker with nothing company-specific gets status "clean", items [] and a short neutral cleanNote such as "No material company news in this window." Never write notes about what could not be verified or found. If a holding moved a lot with no company-specific reason from an allowed source, do not guess a cause.
- Facts only: no buy/sell/hold framing, no predictions, no opinion language.
- market.driver is a short factual summary of the main market driver, including sector-wide moves, with an allowed source. Only include market.dataRelease ({name, actual, expected}) if a data release actually happened in the window; otherwise omit the key.
- market.cryptoDriver ({text, sourceName, sourceUrl}) is optional: only for a crypto-specific event from an allowed source, and never quote prices in it.
- Each ticker item has: headline, summary, sourceName, sourceUrl, pubTime, sourceDepth.

## History (required, so past days stay viewable)
Write your section object on its own (not wrapped in "morning" or "recap") to data/<YYYY-MM-DD>-<mode>.json for today's date, overwriting if it exists. Then open data/index.json (shape {"days":[{"date","morning":bool,"recap":bool}, ...]}, newest first): set today's flag for your mode to true, or add the entry in the right place. Never remove or change other days' entries or files. Also save the section into data.json under your mode's key (this stays the "latest" copy) and leave the other mode's section untouched.

## Finish
Validate that data.json, the dated file and data/index.json are valid JSON. Commit them together on main and push to origin main. If the push fails, retry once after `git pull --rebase origin main`; if it still fails, report the exact error. Then tell the user, briefly: the date, the top one or two stories, how many items are headline-only, and anything dropped (including how many links were paywalled or blocked).

Do not fabricate anything. If something can't be supported by an allowed source at the depth described above, leave it out.
