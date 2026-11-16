# Daily Recap task

First read common.md in this folder; its rules apply. Update ONLY the "recap" section of data.json (mode = recap, commit message "Daily recap <YYYY-MM-DD>"). If the market was closed today (weekend or holiday), do nothing and say so.

- Window: from the previous market close (4:00 PM ET) to today's close (4:00 PM ET). On Monday the window starts at Friday's close.
- Wait for the data: right after cloning, check that prices/<today>-recap.json exists and that filings/<today>-recap.json and news/<today>-recap.json have "final": true. If not, run `git pull` every 2 minutes for up to 25 minutes and continue as soon as they are there. If something is still missing, carry on without it.
- Read prices/<today>-recap.json to see which holdings moved about 3% or more (for example BABA or FUTU) and look for a company-specific reason in your sources.
- THE RECAP COVERS THE WHOLE DAY ON ITS OWN, because it is what is read first the next morning. Read data/<today>-morning.json and keep this morning's stories in the recap, updated with what happened since (how the stock closed, any new development) instead of repeating them word for word. Drop a morning item only if it turned out to be wrong or irrelevant. Then add everything new from the day. Previews of upcoming events do not belong in the recap, but earnings that were actually reported do, with the key reported figures from the filing text.
- Analyst actions: use the day's items from news/<today>-recap.json as described in common.md; do not carry over the morning's analyst item, since the recap file already contains the whole day's actions in one digest.
- Set reportDate to today, periodStart/periodEnd, lastUpdated to now in ET, and populated true. If you correct something already published for the same reportDate, add an entry to revisions.
