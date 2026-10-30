---
name: linkedin-connect-queue
description: Daily LinkedIn connection queue for AI & Automation / D&T analyst roles — reads the companies already in the job-hunt logs, ranks who to connect with, drafts invite notes, never sends anything
metadata:
  type: project
---

Daily task `linkedin-connect-queue` builds Priya Gupta's LinkedIn outreach queue for
entry-level **AI & Automation / D&T analyst** roles in India. It runs alongside
`dt-ai-automation-job-hunt` (portals + careers sites) and `daily-ba-outreach-drafts`
(email drafts), and deliberately covers the third channel: people.

## Hard rules

1. **Never log into LinkedIn, never scrape it, never send an invite or message.**
   LinkedIn's User Agreement bans automated access and enforces it with account
   restrictions and bans. This task only *prepares* outreach. Priya clicks send.
2. **Never create accounts.** Same rule as her other job-hunt tasks.
3. **Honesty**, per `config/profile.json` → `honesty_rules`. She was never titled
   Business Analyst; Somany was Graduate Engineer Trainee (SAP/CRM functional). No
   production SQL, no ML engineering, no invented mutual connections or referrals.
4. **Stay under the cap.** `invites_per_day` is 12 (≈84/week) against LinkedIn's
   ~100–200/week invite ceiling. Do not raise it to "move faster" — a restricted
   account costs her the whole network.

## Step 1 — Build the queue

```
cd <repo>/linkedin-connect-queue
python3 build_queue.py build --open
```

It reads the two existing job-hunt logs, so the companies she is *actually*
applying to rank highest:

- `~/.claude/projects/-Users-priyagupta-Desktop-FullStack-Assignment/memory/project_dt_jobhunt_log.md`
- `~/.claude/projects/-Users-priyagupta-Desktop-FullStack-Assignment/memory/project_ba_outreach_log.md`

Missing logs are skipped silently; the queue falls back to the configured company
tiers. Output lands in `out/queue_<date>.html` (clickable) and `.csv`.

## Step 2 — Report in chat

Tell her, briefly:

- How many targets are queued today, and how many follow-ups are due.
- Which companies rose to the top **because they appear in her application log** —
  that connection is the point of the task.
- Any company in the log that is *not* in `config/profile.json` → `companies`, so
  she can decide whether to add it.
- The path to the HTML.

Do not paste the whole queue into chat. The HTML is the interface.

## Step 3 — After she sends

Each invite she actually sends gets logged so tomorrow's queue skips that person
and the follow-up clock starts:

```
python3 build_queue.py log --company "General Mills" --persona recruiter_inhouse \
                           --name "Full Name" --url "<profile url>"
```

When someone accepts or replies:

```
python3 build_queue.py respond --name "Full Name" --status accepted
```

If she tells you in chat who she sent to, run these for her rather than making her
type them. If she has not reported back, ask once, briefly, and move on — do not
nag across runs.

## Step 4 — Follow-ups

`python3 build_queue.py followups` prints messages due 7+ days after an invite.
These are **messages to an existing connection**, not invites, so they are not
capped — but still never sent automatically. Same honesty rules.

## Notes on the personas

Four, weighted: hiring managers and AI/data leads (40), in-house TA (30), peers
already in the role (20), agency recruiters (10). Peers are the referral path and
convert best in India — the first note must ask about *their move*, never for a job.

## When something looks wrong

- Role shown is the generic fallback (`AI & Automation analyst`) → that company is
  in the tier list but has no live role in the log. Fine, but a real role name from
  the log converts better; check whether the log row parsed.
- A note shows `auto-trimmed` → the role title is unusually long. Shorten it in the
  log or accept the trim.
- Queue is empty → every company/persona pair was contacted inside
  `recontact_company_after_days` (45). Widen the company list rather than lowering it.
