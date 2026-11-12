# linkedin-connect-queue

A daily LinkedIn outreach queue for entry-level **AI & Automation / D&T analyst**
roles in India. It turns the job-hunt logs you already produce into a ranked list
of *people* worth connecting with, with the invite note already written.

It does not touch LinkedIn. It builds URLs and text; you click and send.

## Why it works this way

Automating LinkedIn invites violates LinkedIn's User Agreement and reliably gets
accounts restricted or banned — which destroys the network you are building. Invites
are capped around 100–200/week anyway, so volume was never the lever. What actually
moves the needle is *who* you pick and whether the note is specific. This automates
both of those, and the record-keeping, and leaves the click to you.

## Quick start

```
python3 build_queue.py build --open
```

Opens `out/queue_<date>.html`: one card per target with search links, a note sized
to LinkedIn's 300-character invite limit, and a copy button.

For each card — open a search link, pick someone real who fits, swap
`{first_name}` for their first name, copy, send. Then:

```
python3 build_queue.py log --company "General Mills" --persona recruiter_inhouse --name "Full Name"
```

## Commands

| Command | What it does |
|---|---|
| `build [--limit N] [--logs ...] [--open]` | Build today's ranked queue → HTML + CSV |
| `log --company --persona --name [--url] [--role]` | Record an invite you sent |
| `respond --name --status accepted\|replied\|declined\|ignored` | Update an outcome |
| `followups` | Print follow-up messages due 7+ days after an invite |
| `stats` | Totals, last-7-days count, accept/reply rate |

## How targets are ranked

`score = persona weight + 50 if the company is in your application log + tier bonus`

- Persona weights: hiring manager 40, in-house TA 30, peer in role 20, agency 10
- Applied-to companies get +50, so they dominate the top of the queue — that is the
  whole idea: connect where you already have an application in flight
- Tier 1 (FMCG/consumer MNC) +15, tier 2 (GCC/consulting) +5
- Capped at 2 people per company per run and 12 invites per day
- Any company/persona pair contacted in the last 45 days is skipped

## Free vs Premium

LinkedIn treats personalised invite notes very differently by account type, and
`config/profile.json` -> `linkedin_account` -> `type` must say which you have:

| | Free | Premium |
|---|---|---|
| Personalised notes | ~3 per month | unlimited |
| Note length | 200 chars | 300 chars |

On **premium** every target in the queue gets a note. On **free** the queue spends
the 3 monthly notes on hiring managers and peers first, marks everyone else
`plain invite`, and gives you an *after they accept* DM instead — which has no
length limit and costs nothing from the budget. The monthly count is tracked in the
sent log, so it resets on its own.

Weekly invite volume (~100/week, note or no note) is a separate limit and applies
to both; that is what `invites_per_day` protects.

## Configuration

**`config/profile.json`** — who you are, target titles, locations, filters, company
tiers, and the rate limits. Update `experience_label` / `experience_months` as time
passes, and add companies as your applications spread.

**`config/personas.json`** — the four personas, their LinkedIn search queries, and
the note templates. Notes are tried longest-first; the first that fits 300 chars
wins, so put your best phrasing first and a terse fallback last.

Template fields: `{first}`, `{company}`, `{company_poss}`, `{role}`, `{a_role}`
(role with a/an), `{location}`, `{exp}`.

## State

`state/outreach_sent.csv` — every invite logged, with status and dates. This is the
dedupe source and the follow-up clock. Back it up; losing it means re-contacting
people you have already approached.

## Honesty

`config/profile.json` → `honesty_rules` is enforced by the templates: engineer with
requirement-gathering and low-code delivery experience moving into AI-enabled
business analysis. Never "Business Analyst" as a past title, never production SQL,
never an invented mutual connection. If you edit the templates, keep that true —
a recruiter who catches an inflated claim is a door closed permanently.
