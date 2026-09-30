# 5-minute demo video: recording script

**What's on screen:** the 2-page submission PDF, the terminal, and the GitHub README. Every "Show" step below refers to one of these three.

**Goal of the video (from the brief):** what you found, what you built, what remains unknown.
**Length:** about 4.5 minutes (under the 5-minute limit). Casual tone, around 550 words.

---

## Before you hit record (5 min setup)

1. Open a terminal in the repo and activate the environment:
   ```bash
   cd ~/FDE/campusdesk-fde-assignment
   source .venv/bin/activate
   clear
   ```
2. Increase the terminal font size (Cmd `+` three or four times) so the log is readable in the video.
3. Open these in separate windows, in this order:
   - the **2-page submission PDF** `report/CampusDesk_FDE_Submission_Lakshya_Mewara.pdf` (also in your Downloads folder)
   - the **GitHub repo** in your browser: https://github.com/LAKSHYAMEWARA0025/campusdesk-fde-assignment (README open)
   - the **terminal** from step 1
4. Keep this script on your **phone** (open it from GitHub: `docs/DEMO_SCRIPT.md`) so it doesn't appear in the recording.
5. Do one silent practice run of the pipeline so the first run in the video isn't slow:
   `python pipeline/run_pipeline.py --run-id live_practice`
6. Record with **QuickTime → File → New Screen Recording** (or Loom). Turn the microphone on, record the whole screen, and close notifications (Focus mode on).

> The `live_*` run folders are git-ignored, so running the demo doesn't dirty the repo.

---

## Script

Talk the way you'd explain it to a friend. **Don't read word for word**: glance at the next bullet and say it your way. Around 4–4.5 minutes is perfect.

### 0:00 – 0:30 · Intro
**Show:** PDF **page 1**, the top.

> "Hi, I'm Lakshya, roll number 24bcs10290, and this is my FDE project, CampusDesk.
> So the Dean of a college came with a request: students keep complaining that helpdesk tickets take forever, so let's buy an AI chatbot.
> Instead of just building that, I wanted to first figure out *where* the time is actually going."

### 0:30 – 1:15 · The problem
**Show:** PDF **page 1**. Scroll slowly past the stakeholders, the workflow strip and the problem statement.

> "These are the people involved: the Dean owns the goal, the helpdesk manager runs it day to day, and then there are the triage staff, the department teams and the students.
> This is how a ticket moves. The student raises it, it gets routed to a team, the team works on it, and it gets closed. The red boxes are where things go wrong.
> And the numbers are pretty clear: only 63% of tickets finish on time, and for high-priority ones it's just 21%. So my goal is to get that to 75% in 8 weeks, with the same team and the same tool."

### 1:15 – 2:15 · The pipeline, live
**Show:** terminal. Run:
```bash
python pipeline/run_pipeline.py --run-id live_demo
```
> "Let me run the pipeline.
> It pulls data from four places: a SQL database, a CSV log, a JSON survey file and an API.
> See these yellow warnings? That's the API failing on purpose, like real APIs do. The pipeline just retries, and it checks that all 4,550 records actually came through.
> Then it runs 15 checks on the data. Messy stuff like wrong date formats or missing priorities gets fixed or flagged, but never silently hidden.
> And at the end: 63.1% on time."

### 2:15 – 2:45 · Showing it fails safely
**Show:** terminal. Run:
```bash
python pipeline/run_pipeline.py --run-id live_fail --simulate truncated_events
```
> "Now what if the data is broken? Here I'm cutting half the log file.
> It catches it straight away, the check fails, and it refuses to publish anything. The last good result stays untouched. That's the part I really wanted to get right."

### 2:45 – 3:45 · What I found
**Show:** PDF **page 2**: the tiles at the top, then the chart and bullets.

> "So what's actually slowing things down? Late tickets take 126 hours on average, compared to 42 for on-time ones, and it's not because students reply slowly.
> Four things stood out.
> One: high-priority tickets wait just as long as low ones. Priority is recorded, but nobody uses it.
> Two: when a ticket goes to the wrong team, things fall apart. From 66% on time down to 18%.
> Three: Finance and Academics are the slowest teams, 28% and 45%, versus 87% for IT.
> And four: escalation only kicks in after about 65 hours, which is way past the deadline for urgent tickets."

### 3:45 – 4:15 · What I'd recommend
**Show:** PDF **page 2**, the Recommendation paragraph.

> "So my honest answer is: don't buy the chatbot yet.
> Fix the routing, escalate earlier, and sort queues by deadline. My estimate is that gets us to around 79%.
> But I'd test it with a 2-week pilot first, before promising anything."

### 4:15 – 4:40 · Wrap-up
**Show:** PDF **page 2** (Reliability + unknowns), then the **GitHub repo** with the green badge.

> "One last thing: since the data is synthetic, I could check my pipeline against the true answer, and it's within half a percent.
> What I still don't know is *why* tickets get misrouted, and whether earlier escalation really helps. That's what the pilot is for.
> Everything is on GitHub, with the full README. Thanks for watching!"

---

## After recording

1. Upload the file to Google Drive.
2. Right-click → **Share → General access: "Anyone with the link" → Viewer**.
3. Copy the link and send it over. It goes into the **demo video** box at the bottom of PDF page 2, and into the README.
