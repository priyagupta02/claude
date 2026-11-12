#!/usr/bin/env python3
"""
Build a LinkedIn connection queue for AI & Automation / D&T analyst roles.

Reads the companies and roles you are ACTUALLY applying to out of your existing
job-hunt logs, cross-references the four target personas, and emits a ranked,
deduplicated, daily-capped queue of people to connect with -- each row carrying
a pre-built LinkedIn search URL and a ready personalised note inside LinkedIn's
300-character invite limit.

It never logs into LinkedIn, never scrapes it, and never sends anything.
You click and send; it remembers what you sent and when to follow up.

Usage:
  python3 build_queue.py build [--limit N] [--open]
  python3 build_queue.py log --company "General Mills" --persona recruiter_inhouse \
                             --name "A. Sharma" [--url ...] [--role ...]
  python3 build_queue.py respond --name "A. Sharma" --status accepted|replied|declined
  python3 build_queue.py followups
  python3 build_queue.py stats
"""

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(HERE, "config")
STATE_DIR = os.path.join(HERE, "state")
OUT_DIR = os.path.join(HERE, "out")
SENT_CSV = os.path.join(STATE_DIR, "outreach_sent.csv")

SENT_FIELDS = [
    "date", "company", "persona", "person_name", "person_url",
    "role", "with_note", "note_sent", "status", "status_date", "notes",
]

# Your existing daily-task logs. Missing files are skipped without complaint,
# so this runs fine on a machine that does not have them.
DEFAULT_LOG_PATHS = [
    "/Users/priyagupta/.claude/projects/-Users-priyagupta-Desktop-FullStack-Assignment/memory/project_dt_jobhunt_log.md",
    "/Users/priyagupta/.claude/projects/-Users-priyagupta-Desktop-FullStack-Assignment/memory/project_ba_outreach_log.md",
]

TODAY = dt.date.today()


# ---------------------------------------------------------------- config load

def load_config():
    with open(os.path.join(CONFIG_DIR, "profile.json")) as f:
        profile = json.load(f)
    with open(os.path.join(CONFIG_DIR, "personas.json")) as f:
        personas = json.load(f)
    return profile, personas


# ------------------------------------------------------- application log parse

def _norm(s):
    return re.sub(r"[^a-z0-9&]+", "", (s or "").lower())


def parse_application_logs(paths, all_companies):
    """Pull (company, role, location, source) out of the markdown job-hunt logs.

    Handles two shapes: markdown table rows, and prose that simply mentions a
    known company. Anything we cannot attribute to a known company is ignored.
    """
    by_norm = {_norm(c): c for c in all_companies}
    found = {}

    def record(company, role=None, location=None, source=""):
        key = _norm(company)
        canonical = by_norm.get(key)
        if not canonical:
            return
        entry = found.setdefault(
            canonical, {"company": canonical, "roles": [], "locations": [], "sources": set()}
        )
        if role:
            role = role.strip(" *_|")
            if role and role.lower() not in {r.lower() for r in entry["roles"]}:
                entry["roles"].append(role)
        if location:
            location = location.strip(" *_|")
            if location and location not in entry["locations"]:
                entry["locations"].append(location)
        if source:
            entry["sources"].add(source)

    for path in paths:
        if not os.path.isfile(path):
            continue
        label = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                if line.lstrip().startswith("|") and line.count("|") >= 3:
                    cells = [c.strip() for c in line.strip().strip("|").split("|")]
                    if len(cells) >= 2 and not set(cells[0]) <= set("-: "):
                        record(cells[0], cells[1] if len(cells) > 1 else None,
                               cells[2] if len(cells) > 2 else None, label)
                        continue
                low = line.lower()
                for norm_name, canonical in by_norm.items():
                    if norm_name and norm_name in _norm(low):
                        record(canonical, source=label)

    for entry in found.values():
        entry["sources"] = sorted(entry["sources"])
    return found


# --------------------------------------------------------------- sent-log I/O

def read_sent():
    if not os.path.isfile(SENT_CSV):
        return []
    with open(SENT_CSV, newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f)]


def append_sent(row):
    os.makedirs(STATE_DIR, exist_ok=True)
    exists = os.path.isfile(SENT_CSV)
    with open(SENT_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SENT_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in SENT_FIELDS})


def write_sent_all(rows):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SENT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SENT_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in SENT_FIELDS})


def parse_date(s):
    try:
        return dt.date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


# ------------------------------------------------------------- note rendering

def render_note(templates, limit, **fields):
    """Return the longest note template that fits the invite character limit."""
    for tpl in templates:
        try:
            note = tpl.format(**fields)
        except KeyError:
            continue
        note = re.sub(r"\s+", " ", note).strip()
        if len(note) <= limit:
            return note, False
    # Every variant was too long: hard-trim the shortest at a word boundary.
    note = re.sub(r"\s+", " ", templates[-1].format(**fields)).strip()
    return note[: limit - 1].rsplit(" ", 1)[0] + "…", True


def article_for(phrase):
    """'a' / 'an' by the sound of the first letter. Initialisms like D&T read
    as 'dee', so plain vowel-letter matching is right here."""
    return "an" if (phrase or "")[:1].lower() in "aeiou" else "a"


def possessive(name):
    return name + ("'" if name.endswith("s") else "'s")


def search_url(query, geo_urn=None):
    params = {"keywords": query, "origin": "GLOBAL_SEARCH_HEADER"}
    if geo_urn:
        params["geoUrn"] = json.dumps([geo_urn])
    return "https://www.linkedin.com/search/results/people/?" + urllib.parse.urlencode(params)


def jobs_url(titles, geo_urn=None):
    params = {"keywords": " OR ".join('"%s"' % t for t in titles[:4]), "f_TPR": "r1296000",
              "sortBy": "DD"}
    if geo_urn:
        params["geoId"] = geo_urn
    return "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(params)


# ------------------------------------------------------------- queue building

def build_queue(profile, personas_cfg, applied, sent, limit=None):
    cand = profile["candidate"]
    limits = profile["limits"]
    search_cfg = profile["search"]
    geo = search_cfg.get("india_geo_urn")
    note_limit, _ = note_limit_for(profile, personas_cfg)
    personas = personas_cfg["personas"]
    generic_role = personas_cfg.get("generic_role_fallback", "AI & Automation analyst")

    tier1 = profile["companies"]["tier1_fmcg_consumer"]
    tier2 = profile["companies"]["tier2_gcc_consulting"]

    recontact_days = int(limits.get("recontact_company_after_days", 45))
    recent_pairs = {}
    for row in sent:
        d = parse_date(row.get("date"))
        if d and (TODAY - d).days <= recontact_days:
            recent_pairs.setdefault((_norm(row.get("company")), row.get("persona")), 0)
            recent_pairs[(_norm(row.get("company")), row.get("persona"))] += 1

    rows = []
    for company in tier1 + tier2:
        app = applied.get(company)
        tier_bonus = 15 if company in tier1 else 5
        applied_bonus = 50 if app else 0
        role = (app["roles"][0] if app and app["roles"] else generic_role)
        location = (app["locations"][0] if app and app["locations"]
                    else search_cfg["locations"][0])

        for pkey, p in personas.items():
            if recent_pairs.get((_norm(company), pkey)):
                continue  # already worked this company/persona recently
            note, trimmed = render_note(
                p["notes"], note_limit,
                first="{first_name}", company=company, role=role,
                company_poss=possessive(company),
                a_role="%s %s" % (article_for(role), role),
                location=location, exp=cand["experience_label"],
            )
            queries = [q.format(company=company) for q in p["queries"]]
            rows.append({
                "score": p["weight"] + applied_bonus + tier_bonus,
                "company": company,
                "persona": pkey,
                "persona_label": p["label"],
                "why": p["why"],
                "role": role,
                "location": location,
                "applied": bool(app),
                "applied_sources": ", ".join(app["sources"]) if app else "",
                "queries": queries,
                "urls": [search_url(q, geo) for q in queries],
                "note": note,
                "note_trimmed": trimmed,
            })

    rows.sort(key=lambda r: (-r["score"], r["company"], r["persona"]))

    per_company_cap = int(limits.get("max_per_company_per_run", 2))
    daily_cap = int(limit or limits.get("invites_per_day", 12))
    chosen, counts = [], {}
    for r in rows:
        if len(chosen) >= daily_cap:
            break
        if counts.get(r["company"], 0) >= per_company_cap:
            continue
        counts[r["company"]] = counts.get(r["company"], 0) + 1
        chosen.append(r)

    # Spend the scarce personalised notes on the targets where a note earns its
    # keep: hiring managers and peers. Everyone else gets a plain invite, and the
    # real pitch goes as a message once they accept, where there is no limit.
    _, budget = note_limit_for(profile, personas_cfg)
    remaining = max(0, budget - notes_used_this_month(sent))
    note_first = {"hiring_manager": 0, "peer_in_role": 1, "recruiter_inhouse": 2,
                  "agency_recruiter": 3}
    for i, r in enumerate(sorted(chosen, key=lambda r: (note_first.get(r["persona"], 9),
                                                        -r["score"]))):
        r["with_note"] = i < remaining
    for r in chosen:
        r["after_accept"] = personas_cfg["followup_after_accept"].format(
            first="{first_name}", company=r["company"], exp=cand["experience_label"])
    return chosen, rows


def notes_used_this_month(sent):
    """Personalised notes are a scarce monthly resource on a free account."""
    n = 0
    for row in sent:
        if (row.get("with_note") or "").strip().lower() not in ("yes", "true", "1"):
            continue
        d = parse_date(row.get("date"))
        if d and (d.year, d.month) == (TODAY.year, TODAY.month):
            n += 1
    return n


def note_limit_for(profile, personas_cfg):
    acct = profile.get("linkedin_account") or {}
    if not acct:
        return personas_cfg.get("note_char_limit", 300), 999
    premium = (acct.get("type") or "free").lower() == "premium"
    limit = acct.get("note_char_limit_premium" if premium else "note_char_limit_free",
                     300 if premium else 200)
    budget = 999 if premium else int(acct.get("personalized_notes_per_month", 3))
    return int(limit), budget


def due_followups(profile, personas_cfg, sent):
    days = int(profile["limits"].get("followup_after_days", 7))
    cand = profile["candidate"]
    tpl = personas_cfg["followup_after_accept"]
    out = []
    for row in sent:
        if (row.get("status") or "").lower() not in ("", "sent", "accepted"):
            continue
        d = parse_date(row.get("date"))
        if not d or (TODAY - d).days < days:
            continue
        msg = tpl.format(first=(row.get("person_name") or "there").split()[0],
                         company=row.get("company", ""), exp=cand["experience_label"])
        out.append({"row": row, "age_days": (TODAY - d).days, "message": msg})
    out.sort(key=lambda x: -x["age_days"])
    return out


# ------------------------------------------------------------------- HTML out

HTML_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn Connect Queue</title>
<style>
:root{--bg:#fbfaf9;--fg:#1a1a18;--mut:#6b6a66;--line:#e5e2dd;--card:#fff;--acc:#2d5f4f;--warn:#9a5b1d;--chip:#f0eeea}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#1a1a18;--fg:#f0eeea;--mut:#a3a19b;--line:#33322e;--card:#232320;--acc:#7fb79f;--warn:#d9a05b;--chip:#2b2a27}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;padding:24px 16px 64px}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:20px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px}
.chip{background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:4px 11px;font-size:12px;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.top{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:3px}
.rank{font-variant-numeric:tabular-nums;color:var(--mut);font-size:12px;min-width:20px}
.co{font-weight:650;font-size:16px}
.tag{font-size:11px;border:1px solid var(--line);border-radius:5px;padding:1px 6px;color:var(--mut)}
.tag.ap{color:var(--acc);border-color:var(--acc)}
.tag.note{color:var(--warn);border-color:var(--warn);font-weight:600}
.plain{font-size:12.5px;color:var(--mut);margin-bottom:7px}
.meta{color:var(--mut);font-size:13px;margin-bottom:9px}
.why{color:var(--mut);font-size:12.5px;font-style:italic;margin-bottom:10px}
.lnks{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
a.btn,button{font:inherit;font-size:12.5px;border:1px solid var(--line);background:var(--chip);color:var(--fg);
 border-radius:7px;padding:5px 10px;text-decoration:none;cursor:pointer;display:inline-block}
a.btn:hover,button:hover{border-color:var(--acc);color:var(--acc)}
textarea{width:100%;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);
 font:inherit;font-size:13.5px;padding:9px 10px;resize:vertical;min-height:72px}
.row2{display:flex;align-items:center;gap:9px;margin-top:7px;flex-wrap:wrap}
.cnt{font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums}
.cnt.over{color:var(--warn);font-weight:600}
.note{background:var(--chip);border-left:3px solid var(--acc);border-radius:0 8px 8px 0;padding:11px 13px;margin-bottom:20px;font-size:13px;color:var(--mut)}
h2{font-size:15px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
code{background:var(--chip);border-radius:4px;padding:1px 5px;font-size:12px}
</style></head><body><div class="wrap">
"""

HTML_FOOT = """
<script>
function cp(id,b){const t=document.getElementById(id);navigator.clipboard.writeText(t.value||t.textContent)
 .then(()=>{const o=b.textContent;b.textContent='Copied';setTimeout(()=>b.textContent=o,1200)});}
document.querySelectorAll('textarea[data-lim]').forEach(t=>{
 const c=document.getElementById(t.id+'-c'),lim=+t.dataset.lim;
 const u=()=>{c.textContent=t.value.length+'/'+lim;c.classList.toggle('over',t.value.length>lim)};
 t.addEventListener('input',u);u();});
</script></div></body></html>
"""


def render_html(profile, personas_cfg, chosen, applied, followups, total_candidates):
    cand = profile["candidate"]
    lim, budget = note_limit_for(profile, personas_cfg)
    acct = (profile.get("linkedin_account") or {}).get("type", "free")
    with_note_n = sum(1 for r in chosen if r.get("with_note"))
    e = html.escape
    p = [HTML_HEAD]
    p.append("<h1>LinkedIn connect queue</h1>")
    p.append('<div class="sub">%s &middot; generated %s &middot; %d of %d candidate targets, '
             "capped at %d/day</div>"
             % (e(cand["full_name"]), TODAY.isoformat(), len(chosen), total_candidates,
                profile["limits"]["invites_per_day"]))

    p.append('<div class="bar">')
    p.append('<span class="chip">%d companies in your application log</span>' % len(applied))
    p.append('<span class="chip">%s account &middot; note limit %d chars</span>' % (e(acct), lim))
    p.append('<span class="chip">%d of today\'s %d get a note (%s/month budget)</span>'
             % (with_note_n, len(chosen), "unlimited" if budget > 900 else budget))
    p.append('<span class="chip">%d follow-ups due</span>' % len(followups))
    p.append('<a class="btn" target="_blank" rel="noopener" href="%s">Fresh job postings &rarr;</a>'
             % e(jobs_url(profile["search"]["target_titles"], profile["search"].get("india_geo_urn"))))
    p.append("</div>")

    p.append('<div class="note"><b>How to work this queue.</b> Open a search link, pick a real person '
             "who fits, then look at the badge. <b>WITH NOTE</b> &rarr; click Connect, choose "
             "\u201cAdd a note\u201d, paste the note with <code>{first_name}</code> replaced. "
             "<b>PLAIN INVITE</b> &rarr; just click Connect with no note, and send the "
             "<i>after they accept</i> message as a normal DM once they do &mdash; that has no "
             "character limit and does not spend your monthly note budget. Record each one with "
             "<code>build_queue.py log</code> so tomorrow skips them. Send by hand: automating "
             "invites gets accounts restricted.</div>")

    p.append("<h2>Today&rsquo;s queue</h2>")
    for i, r in enumerate(chosen, 1):
        nid = "n%d" % i
        p.append('<div class="card"><div class="top"><span class="rank">%d</span>'
                 '<span class="co">%s</span><span class="tag">%s</span>%s</div>'
                 % (i, e(r["company"]), e(r["persona_label"]),
                    ("" if budget > 900 else
                     ('<span class="tag note">WITH NOTE</span>' if r.get("with_note")
                      else '<span class="tag">plain invite</span>'))
                    + ('<span class="tag ap">applied</span>' if r["applied"] else "")))
        p.append('<div class="meta">%s &middot; %s%s</div>'
                 % (e(r["role"]), e(r["location"]),
                    " &middot; from " + e(r["applied_sources"]) if r["applied_sources"] else ""))
        p.append('<div class="why">%s</div>' % e(r["why"]))
        p.append('<div class="lnks">')
        for j, (q, u) in enumerate(zip(r["queries"], r["urls"]), 1):
            p.append('<a class="btn" target="_blank" rel="noopener" href="%s" title="%s">Search %d</a>'
                     % (e(u), e(q), j))
        p.append("</div>")
        if r.get("with_note"):
            p.append('<textarea id="%s" data-lim="%d" spellcheck="false">%s</textarea>'
                     % (nid, lim, e(r["note"])))
            p.append('<div class="row2"><button onclick="cp(\'%s\',this)">Copy note</button>'
                     '<span class="cnt" id="%s-c"></span>%s</div></div>'
                     % (nid, nid,
                        '<span class="cnt over">auto-trimmed</span>' if r["note_trimmed"] else ""))
        else:
            aid = nid + "a"
            p.append('<div class="plain">Connect with <b>no note</b>. Send this as a DM once '
                     "they accept:</div>")
            p.append('<textarea id="%s" data-lim="1200" spellcheck="false">%s</textarea>'
                     % (aid, e(r["after_accept"])))
            p.append('<div class="row2"><button onclick="cp(\'%s\',this)">Copy follow-up</button>'
                     '<span class="cnt" id="%s-c"></span></div></div>' % (aid, aid))

    if followups:
        p.append("<h2>Follow-ups due</h2>")
        for k, f in enumerate(followups, 1):
            row, fid = f["row"], "f%d" % k
            p.append('<div class="card"><div class="top"><span class="co">%s</span>'
                     '<span class="tag">%s</span><span class="tag">%d days ago</span></div>'
                     % (e(row.get("person_name") or "(unnamed)"),
                        e(row.get("company", "")), f["age_days"]))
            p.append('<textarea id="%s" data-lim="1000" spellcheck="false">%s</textarea>' % (fid, e(f["message"])))
            p.append('<div class="row2"><button onclick="cp(\'%s\',this)">Copy message</button>'
                     '<span class="cnt" id="%s-c"></span></div></div>' % (fid, fid))

    p.append(HTML_FOOT)
    return "".join(p)


# -------------------------------------------------------------------- commands

def cmd_build(args):
    profile, personas_cfg = load_config()
    all_companies = (profile["companies"]["tier1_fmcg_consumer"]
                     + profile["companies"]["tier2_gcc_consulting"])
    log_paths = args.logs or DEFAULT_LOG_PATHS
    applied = parse_application_logs(log_paths, all_companies)
    sent = read_sent()
    chosen, every = build_queue(profile, personas_cfg, applied, sent, args.limit)
    followups = due_followups(profile, personas_cfg, sent)

    os.makedirs(OUT_DIR, exist_ok=True)
    html_path = os.path.join(OUT_DIR, "queue_%s.html" % TODAY.isoformat())
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(profile, personas_cfg, chosen, applied, followups, len(every)))

    csv_path = os.path.join(OUT_DIR, "queue_%s.csv" % TODAY.isoformat())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "company", "persona", "role", "location", "applied",
                    "with_note", "note", "note_chars", "after_accept",
                    "search_url_1", "search_url_2"])
        for i, r in enumerate(chosen, 1):
            u = r["urls"] + ["", ""]
            w.writerow([i, r["company"], r["persona"], r["role"], r["location"],
                        "yes" if r["applied"] else "",
                        "yes" if r.get("with_note") else "no",
                        r["note"] if r.get("with_note") else "", len(r["note"]),
                        "" if r.get("with_note") else r["after_accept"], u[0], u[1]])

    found = sorted(applied) or ["(none yet)"]
    print("Application log -> %d companies: %s" % (len(applied), ", ".join(found)))
    missing = [p for p in log_paths if not os.path.isfile(p)]
    for m in missing:
        print("  note: log not found, skipped -> %s" % m)
    nlim, nbudget = note_limit_for(profile, personas_cfg)
    used = notes_used_this_month(sent)
    print("Queue: %d targets today (%d possible), %d follow-ups due"
          % (len(chosen), len(every), len(followups)))
    print("Notes: %d of today's targets get a personalised note (%s chars max); "
          "monthly budget %s, used %d"
          % (sum(1 for r in chosen if r.get("with_note")), nlim,
             "unlimited" if nbudget > 900 else nbudget, used))
    print("  HTML: %s" % html_path)
    print("  CSV : %s" % csv_path)
    if args.open:
        os.system('open "%s" >/dev/null 2>&1 || xdg-open "%s" >/dev/null 2>&1 &'
                  % (html_path, html_path))
    return 0


def cmd_log(args):
    profile, personas_cfg = load_config()
    if args.persona not in personas_cfg["personas"]:
        print("Unknown persona %r. Valid: %s"
              % (args.persona, ", ".join(personas_cfg["personas"])), file=sys.stderr)
        return 2
    append_sent({
        "date": args.date or TODAY.isoformat(), "company": args.company,
        "persona": args.persona, "person_name": args.name, "person_url": args.url or "",
        "role": args.role or "", "with_note": "yes" if args.with_note else "no",
        "note_sent": args.note or "", "status": "sent",
        "status_date": "", "notes": "",
    })
    print("Logged: %s / %s / %s" % (args.company, args.persona, args.name))
    return 0


def cmd_respond(args):
    rows = read_sent()
    hits = [r for r in rows if args.name.lower() in (r.get("person_name") or "").lower()]
    if not hits:
        print("No sent record matching %r." % args.name, file=sys.stderr)
        return 1
    if len(hits) > 1 and not args.all:
        print("%d records match %r; re-run with --all or a more specific name:" % (len(hits), args.name))
        for r in hits:
            print("  %s  %s  %s" % (r["date"], r["company"], r["person_name"]))
        return 1
    for r in hits:
        r["status"] = args.status
        r["status_date"] = TODAY.isoformat()
    write_sent_all(rows)
    print("Updated %d record(s) to %s." % (len(hits), args.status))
    return 0


def cmd_followups(args):
    profile, personas_cfg = load_config()
    fs = due_followups(profile, personas_cfg, read_sent())
    if not fs:
        print("No follow-ups due.")
        return 0
    for f in fs:
        r = f["row"]
        print("\n--- %s (%s) - sent %s, %d days ago"
              % (r.get("person_name"), r.get("company"), r.get("date"), f["age_days"]))
        print(f["message"])
    return 0


def cmd_stats(args):
    rows = read_sent()
    if not rows:
        print("Nothing sent yet.")
        return 0
    by_status, by_persona = {}, {}
    for r in rows:
        by_status[r.get("status") or "sent"] = by_status.get(r.get("status") or "sent", 0) + 1
        by_persona[r.get("persona")] = by_persona.get(r.get("persona"), 0) + 1
    wk = sum(1 for r in rows
             if (d := parse_date(r.get("date"))) and (TODAY - d).days < 7)
    print("Total invites logged: %d   (last 7 days: %d)" % (len(rows), wk))
    print("By status : " + ", ".join("%s=%d" % kv for kv in sorted(by_status.items())))
    print("By persona: " + ", ".join("%s=%d" % kv for kv in sorted(by_persona.items())))
    accepted = sum(v for k, v in by_status.items() if k in ("accepted", "replied"))
    if rows:
        print("Accept/reply rate: %.0f%%" % (100.0 * accepted / len(rows)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="build today's connection queue")
    b.add_argument("--limit", type=int, help="override invites_per_day")
    b.add_argument("--logs", nargs="*", help="application log paths to read")
    b.add_argument("--open", action="store_true", help="open the HTML when done")
    b.set_defaults(fn=cmd_build)

    l = sub.add_parser("log", help="record an invite you sent")
    l.add_argument("--company", required=True)
    l.add_argument("--persona", required=True)
    l.add_argument("--name", required=True)
    l.add_argument("--url")
    l.add_argument("--role")
    l.add_argument("--note")
    l.add_argument("--with-note", dest="with_note", action="store_true",
                   help="you attached a personalised note (counts against the monthly budget)")
    l.add_argument("--date")
    l.set_defaults(fn=cmd_log)

    r = sub.add_parser("respond", help="mark an invite accepted/replied/declined")
    r.add_argument("--name", required=True)
    r.add_argument("--status", required=True,
                   choices=["accepted", "replied", "declined", "ignored"])
    r.add_argument("--all", action="store_true")
    r.set_defaults(fn=cmd_respond)

    f = sub.add_parser("followups", help="show follow-up messages that are due")
    f.set_defaults(fn=cmd_followups)

    s = sub.add_parser("stats", help="response-rate summary")
    s.set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    if not getattr(args, "fn", None):
        args = ap.parse_args(["build"])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
