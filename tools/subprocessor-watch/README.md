# Subprocessor Watch

> A daily check of popular SaaS vendors' public subprocessor lists: who they send your data to, what changed, and which of those companies recently had a security incident.

> **In constant development, for professional education.** This is a learning project built in public. It uses public data only, it has real limitations (listed below), and it is not legal, compliance or security advice.

Open `site/index.html` for the page. It has findings, search, a "my stack" view, incident exposure, recent changes and concentration risk. `CHANGELOG.md` has the same information as text.

---

## Why this matters (the GRC idea)

When you buy a SaaS product, your data usually doesn't stay with that vendor. It flows on to *their* suppliers: cloud hosts, AI model providers, support desks. Under privacy laws like GDPR, vendors publish these "subprocessors" in a list, but the lists are long, change quietly, and almost nobody reads them. Those suppliers are your **fourth parties**, and their incidents become your incidents.

Two examples from this tool's own data (as of 2026-11-14):
- **Concentration risk:** Google sits behind all 15 watched vendors, AWS behind 14 and OpenAI behind 12. One outage or breach there reaches most of the stack at once.
- **A disclosure gap:** Notion publicly confirmed it was affected by the October 2026 Fireworks AI incident, but Fireworks AI is not on Notion's public subprocessor list. That's a question to ask the vendor.

Related controls (our own paraphrase): ISO/IEC 27001 Annex A **5.19–5.22**, on managing information security in supplier relationships, including monitoring supplier changes. NIST CSF 2.0 **GV.SC** covers supply-chain risk management.

## What it does

Every day (GitHub Actions, 06:17 UTC), it:
1. **Reads each vendor's public subprocessor page** (15 vendors today). Plain pages are fetched directly. Pages drawn by JavaScript (Vanta trust centers, Notion) are rendered in a headless browser.
2. **Extracts the companies** (name, purpose, location) and gives each one a stable ID. "AWS", "Amazon Web Services, Inc." and "Amazon Web Services EMEA SARL" all become `amazon-web-services`.
3. **Compares with yesterday** and records every addition, removal or change, with the date and a link to the source (`data/changes.jsonl`).
4. **Scans five security-news feeds** for articles that name one of these fourth parties next to incident words. These become **leads to review**.
5. **Matches the incident watchlist** (`incidents.yaml`, hand-curated with sources) against every list. It flags exposed vendors and disclosure gaps.
6. **Rebuilds the page and changelog**, and commits only if something actually changed.

## Quick start

```bash
cd tools/subprocessor-watch
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium   # only needed for JavaScript-drawn pages

.venv/bin/python -m pytest -q                     # tests (no internet needed)
.venv/bin/python -m subprocessor_watch            # full run: vendors + news, rebuilds the page
.venv/bin/python -m subprocessor_watch --render-only     # rebuild the page from stored data
.venv/bin/python -m subprocessor_watch.spotcheck         # compare extraction with the live pages
```

## How it works: decisions

**Git history is the audit trail.** Every change is a dated commit with a source link, so "when did vendor X add company Y?" has a verifiable answer.

**One config entry per vendor, one generic reader.** Every vendor formats its page differently: tables, merged cells, header rows written as ordinary cells, collapsed sections, ten rows per page. `vendors.yaml` says which tables and columns to read, and one reader handles all of them. Adding a vendor is a few lines of config plus a review.

**Vendors are added by hand, not on demand.** "Type any vendor and fetch it live" sounds better, but it would need a paid server, invite abuse, and produce lists nobody had checked. In risk work a wrong list is worse than no list.

**A safety valve against silent breakage.** If a page suddenly yields nothing, or the list shrinks by more than half, the tool assumes its reader broke (a redesign), not that half the suppliers left. It keeps the previous list, records no removals, and marks the vendor `parse_error`.

**Changes the vendor didn't make are not reported.** Re-ordered rows, punctuation or case edits, and our own name-matching improvements (aliases) never show up as vendor changes.

**Generated files are regenerated, never merged by hand.** If someone pushes while the daily run is working, the bot's page and data can conflict with the newer `main`. `publish.sh` doesn't try to merge them. It moves to the latest `main`, runs the watcher again there, and pushes, retrying up to 3 times.

**The first run is a baseline.** A new vendor's whole list is recorded once, not announced as 30 "additions".

**Incidents: a human decides what is real.** The news scan produces leads. Name matching is noisy: "Warp", "Plain" and "Front" are also ordinary words, and Google is in the news every day. So names that are common words are skipped, very large companies only match when the name and a strong incident word are in the headline, and only a person moves a lead into `incidents.yaml`, with a source.

**A page that is safe with untrusted text.** Everything on the page comes from other companies' websites or from news feeds. All text is escaped. The script inserts data only as plain text. The page loads nothing from the internet, and a strict Content-Security-Policy allows only its own style and script, identified by hash. It also works with JavaScript switched off.

**Polite collection.** It respects `robots.txt`, identifies itself with a generic bot name, visits once a day, pauses between sites, and never goes behind a login.

## How the output was checked

- **72 automated tests** run on saved copies of the vendors' tables and on throwaway folders, never on live sites. They cover extraction per vendor, name matching, change detection (added, removed, changed, re-ordered, punctuation-only), the safety valve, incident matching, news matching (including XML-bomb protection), page escaping and the security policy.
- **A live spot-check** (`spotcheck.py`) compares what we extract with each vendor's whole live page. It reports tables we didn't read, names we extracted that aren't on the page, and watchlist companies mentioned outside the tables. Tables skipped on purpose (a vendor's own companies, change logs) are recorded with the reason.
- **The page was checked in a real browser:** search, "my stack", saved choices, phone width, no-JavaScript mode, no security-policy errors.
- **Mistakes caught along the way**, kept here because they show why the checks matter:
  - Notion hides some sections behind collapsed toggles, so the first version read 26 of its 29 subprocessors. The spot-check exists because of this.
  - Merged table cells on HubSpot made the second row of Google's entry look like an unnamed "AI Service Provider". It was briefly reported as a finding before the reader learned about merged cells.
  - An early "AI everywhere" figure counted Google as an AI provider (most vendors list it for hosting). The figure was corrected before publishing.

## What a commercial tool does better

Third-party risk platforms (SecurityScorecard, BitSight, Black Kite, UpGuard, Panorays, and others) offer:
- Thousands of vendors instead of 15, with fourth-party maps built from many signals, not only published lists
- Real-time incident intelligence, dark-web monitoring and analyst-verified breach data
- Contract and questionnaire workflows, risk scoring, and integration with your vendor inventory
- Coverage of pages this tool can't read (PDFs, login-only trust centers)

This tool shows the idea small, free and transparent: every number can be traced back to a public page.

## Limitations

- **15 vendors, chosen by hand.** Some popular apps aren't covered: their lists sit behind a login (Linear), block automated visits (Perplexity, ClickUp), have moved (Slack, Dropbox, Zendesk), or aren't in table form (Canva, Intercom, Cursor).
- **Some sites block automated visits from cloud servers.** OpenAI's page answers GitHub's servers with "HTTP 403", even though it opens fine from a home connection. The tool respects that and doesn't try to get around it. It keeps the last list it read successfully and shows "couldn't read since …" on the page. The daily job only fails when someone needs to act: tests fail, a page layout changes, or a vendor stays unreadable for 3 days or more.
- **Published lists only.** A vendor can use a company without listing it, as the Notion and Fireworks AI case shows. An empty result means "not listed", not "not used".
- **Extra rows of merged cells are skipped.** When a company spans two rows, the second row's details (often a second product or purpose) aren't captured yet.
- **Page redesigns can break a vendor's reader.** The safety valve and spot-check catch this, but a person has to fix the config.
- **Incident leads are noisy and incomplete.** Five news feeds, keyword matching, and common-word names skipped. Leads can be irrelevant, and real incidents can be missed.
- **The incident watchlist is curated by hand** and only as current as its last update.
- **Monitoring started on 2026-11-13.** Changes before that date aren't recorded.
- **No sign-off on legal meaning.** Subprocessor names are shown exactly as each vendor lists them. Nothing here says a vendor did anything wrong.

## Data format

Records use the shared fields across these tools: `vendor_id`, `subprocessor_id`, `source`, `date` (see `schema.json`).
- `data/vendors/<vendor>.json`: the current list. Each entry's `date` is when it was first seen.
- `data/changes.jsonl`: append-only change events (`added` / `removed` / `modified`, with before and after).
- `data/incident_leads.json`: news leads from the last 30 days.
- `incidents.yaml`: the curated incident watchlist, every entry with public sources.

## Ethics
Public pages and public news feeds only. One visit per day per page. No personal data is collected. The goal is better vendor questions, not accusations.

## How I built this with AI

I built this with an AI coding assistant (Claude Code). My part was deciding *what* to build and *why*: which vendors matter, what counts as a finding, what a hiring manager or risk analyst should see first, and when to say "that number looks wrong". The AI wrote most of the code and tests, researched vendor pages and incident sources, and ran the checks.

What worked: insisting that every claim on the page has a source, and that every headline number has a test that could prove it wrong. What the AI got wrong, and how it was caught:
- It missed Notion's collapsed sections. I caught it by asking about a breach I remembered.
- It reported a fake "unnamed AI provider". That was caught when a later page change exposed the merged-cell problem.
- It overcounted AI providers. Caught by writing a test for the claim.

The lesson for AI-assisted GRC work: the AI is fast, but verification still has to be designed in.

## License
[MIT](LICENSE) for the code. The subprocessor lists, incident reports and news items belong to their publishers. They are summarized, with a link to the original source.
