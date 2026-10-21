# Puck Report autopilot (run instructions)

Same content as the `puck-report-autopilot` skill. Scheduled runs read this file after cloning, so they work even if the skill isn't installed.

Puck Report is Karthik's fan-run NHL Facebook page. Produce the day's content with no human in the loop. All times in IST. Never stop to ask questions: make the reasonable call and note it in the summary.

## 0. Workspace
    git clone --depth 1 https://github.com/karthizZZ/puck-report ~/puck-report
    cd ~/puck-report && python3 puck_toolkit.py setup && mkdir -p out
README.md documents every spec field; examples/ has a spec per command.

## 1. Slate
fetch_sports_data(scores, nhl). Last night = start_time between 20:00 UTC yesterday and 08:00 UTC today. Only status closed/complete. game_stats for each final: score, periods, OT (team overtime_goals > 0) / SO (any player shootout.goals), shots, hits, faceoff %, PP goals/opps, blocked shots, scorers, assists, three stars, goalie saves (opponent shots - goals allowed, excluding empty-net goals). Then standings for records.

## 2. Accuracy
Only feed/NHL.com/named reputable sources found this run. Never guess names: write "+2 more goals" or "Toronto's goalie". Feed beats news sites on scores. Conflicting player facts: leave out. Injuries/trades need a named source. Medical emergencies: team wording only.

## 3. What to make
- EARLY run (~9:30 IST): recap videos for the 2 best finished games.
- LATE run (~11:30 IST): full score card (whole slate), recaps for the 1-2 best games the early run did not cover (read the Drive doc "Puck Report - <YYYY-MM-DD> (early)" in folder 1NiT_BHUCd4gZ5pqjl7lbMS2qlUG-kTbA), 3 news story reels, plus an injury list reel only when there are 3+ new injuries with timelines.
Best game: comeback or OT/SO > record/milestone > one-goal game > 3+ point star or hat trick > upset > blowout.

## 4. Specs (write to out/, run `python3 puck_toolkit.py <cmd> out/x.json`)
- scores: {"out":"last_night_<date>.mp4","tag":"FINALS · <MON DD>","games":[[W,ws,L,ls,"OT"|"SO"|""],...]}
- recap (graphics only, 9-11 slides): hook -> score -> periods -> turning point (photo_text w/o photo or tiles) -> star (tiles) -> scorers (list, foot "+N more goals") -> goalie (tiles) -> numbers (winner left) -> losing side -> what it means (tiles: records, next opponent). Hook lines ~14 chars, names ~18 chars, tile labels 1-2 words.
- reel story: {"kind":"story","tag","headline","sub","items":[2-4 items, max 10 words each],"question","source"}
- reel list: {"kind":"list","tag","title","sub","note","rows":[[TEAM,name,injury,STATUS]]}, STATUS one of DAY-TO-DAY, WEEK-TO-WEEK, IR, 1-2 WKS, SEASON, LONG-TERM.

## 5. Verify
Read every <out>_check.png: look for text cut off, overlaps, empty slides, the wrong winner highlighted, missing logos. Fix and re-render (max 2 tries). Re-check every number.

## 6. Deliver
1. SendUserFile all MP4s (+ score PNG), status proactive.
2. Google Doc in folder 1NiT_BHUCd4gZ5pqjl7lbMS2qlUG-kTbA titled "Puck Report - <YYYY-MM-DD> (early|late)": per file give title, caption (2-3 sentences, ends with a real question), ~8 hashtags (#NHL #PuckReport + team tags), and a suggested IST post time (spread 5:30 PM-3:30 AM, 3-5 posts/day). Early doc also lists the games covered.
3. SendUserMessage: short summary, doc link, facts left out and why, games still in progress.
No vote-baiting captions. Lead with the key fact (Facebook truncates at ~125 chars).

## 7. Failures
No finals: one-line message, stop. A render crash: fix and retry once, else skip and report. Clone failure: one-line message, stop. Never post to Facebook.
