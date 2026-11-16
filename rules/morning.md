# Morning Brief task

First read common.md in this folder; its rules apply. Update ONLY the "morning" section of data.json (mode = morning, commit message "Morning brief <YYYY-MM-DD>").

- Window: from the previous market close (4:00 PM ET) to now. On Monday the window starts at Friday's close, so the weekend is rolled up.
- Get the current date with the current_time tool.
- Wait for the final snapshot, but only briefly: right after cloning, if filings/<today>-morning.json or news/<today>-morning.json does not have "final": true, run `git pull` every 2 minutes for at most 8 minutes (the brief must be out by 8:30 AM ET), then continue with what exists.
- The price file usually is not ready when this task runs, so do not wait for it. If prices/<today>-morning.json exists, you may read it to see which holdings are moving about 3% or more.
- market.calendar lists today's scheduled events: earnings with times, and economic data releases (use the official feeds and company releases). Previews belong here, for example "Alphabet reports after the close". Cite an allowed source for each.
- market.driver covers what is moving markets overnight and pre-market.
- Set reportDate to today, periodStart/periodEnd to the window covered, lastUpdated to now in ET, and populated true.
