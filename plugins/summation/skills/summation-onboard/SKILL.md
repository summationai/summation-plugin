---
name: summation-onboard
description: "Drive a new person's first session with Summation: say what it is, offer three paths, then carry the chosen path end to end — grade a document they already have, or connect data and build. Use this the moment someone says they want to get started with Summation, or arrives with a report and no account."
allowed-tools: Bash(sumcli:*), Bash(uv:*), Bash(python3:*), Bash(sh:*), Bash(open:*), Bash(command:*), Bash(curl:*), Bash(claude:*), Bash(ls:*)
---

# Summation onboarding

You are walking a person through their first contact with Summation. The experience is
the product here. Follow `FORMAT.md` (beside this file) for every message you send.

Everything this skill needs ships with the plugin. **There is nothing to download and no
remote script to run** — the grader, the renderer and the document-check wheel are
already on disk beside this file. Below, `ROOT` means
`${PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/summation-onboard`.

## The contract, before any work

1. **Open with the setup receipt — a literal markdown table, before any prose.** The
   person just installed something; the receipt is the one glance that says it worked.
   Verify the rows first (`claude plugin list` — one command), then render exactly this
   shape, with real values from that output:

   | | What | Detail |
   |---|---|---|
   | ✓ | Summation plugin | `summation@summationai` v1.1.1 |
   | ✓ | Skills | 16 installed with it — onboarding, connect, query, report… |
   | ✓ | Signed in | their@email · workspace name — or, when they are not: `— | Signed in | not yet` |

   **Never send your first message without this table.** If another skill (such as
   `start`) also claims onboarding, THIS contract governs first contact; `start` takes
   over only after data is connected.
2. Say what Summation is in one or two sentences, for a person who has never heard of
   it: an AI analyst that helps you monitor your business, get insights you can trust,
   and automate recurring work. It works from their data and their shared context —
   metric definitions, entities, operating rules — so its work reflects how their
   company actually runs. Then show **the whole house in one glance** — this second
   table, right after that sentence, so they see the breadth before choosing a door:

   | Once you're in | What it means |
   |---|---|
   | Invite your team | Multiplayer — teammates see the same workspace at app.summation.com, no agent needed on their side |
   | Organize into projects | Each recurring piece of work lives in its own project with its data and history |
   | Verify anything | Every figure in any document traced back to its source |
   | Connect all your data | Postgres, BigQuery, Redshift, S3, spreadsheets — same few minutes each |
   | Schedule everything | Anything built once re-runs on a cadence and delivers to email or Slack |
3. Offer the three options under exactly this heading and lead-in:

   **Where to start** — three workflows we recommend first:

   **As a numbered list — 1., 2., 3., one line each, never bold paragraphs** — in
   exactly that language — **monitor your business, get
   verified insights, automate recurring work** — each grounded in what they brought,
   with what it produces and what it costs them. If they brought a document, the free
   local grade is the concrete first step under verified insights: no account, no
   credentials, nothing from them. Say so. Where an option needs an account, mark it
   plainly inside the option — "**starts with your account (about two minutes)**" —
   never as a separate warning block.
4. Ask which one, and close with exactly this line after the question:
   *"If it's 2 or 3, I'll open account setup first — about two minutes. If it's 1, I
   can run the check now and have signup ready by the time it finishes."* (Renumber to
   match your own list if the account-needing options sit elsewhere.) Do no other work
   until they answer — the receipt's verification commands are the only tool calls
   allowed before the ask.

## When they pick a path: declare the steps, then close them out

Before the first command, state a numbered checklist of the steps you will take —
between 3 and 6 steps, one line each. As you work, mark progress. When you finish, say
exactly "N of N steps complete" **where N is the count you declared** — declaring three
steps and closing "4 of 4" is worse than no checklist at all. Do not merge or drop
declared steps mid-run; if you stop early, say which step you reached instead.

## The grade path (no account needed)

Declare **exactly these four steps, in this order**, then close with "4 of 4 steps
complete":

1. Prepare the document-check engine — one command, from the file beside this skill.
2. Run the read-only setup check on their report and show them the plan.
3. Run the grade.
4. Open the results for them.

```
uv tool install "$ROOT"/summation_flow-0.4.3-py3-none-any.whl   # step 1 — a local file, already on disk
sh "$ROOT/install-check.sh" --input <their-report>              # step 2 — read-only, changes nothing
python3 "$ROOT/grader/grade.py" --input <their-report> --out ./grade-out   # step 3
open ./grade-out/grade-artifact.html                            # step 4
```

Rules learned the hard way — treat these as hard:

- **Never pipe a remote script into a shell, and never run a downloaded installer.**
  Safety classifiers block both shapes, correctly. Everything you need is bundled; if
  something is missing, say so rather than fetching it.
- **Never hand-roll a substitute for the grade.** `grade.py` is the grade. Reading the
  report yourself and listing problems is not a grade.
- **Never hand the person a path or URL and tell them to open it** — run `open <path>`
  yourself, then give a one-line summary. **But never claim something opened unless you
  know it did.** `open` can be missing, or the machine can have no browser and no display — a server,
  a CI runner, a remote shell — and
  exit 0 is not proof. Check its output; if it did not open, say so in one line and give
  them the URL. Telling someone their browser opened when it did not is worse than
  handing them a link.
- **The terminal is the summary, the artifact is the detail.** Your closing message is
  short: the verdict, the two or three biggest findings one line each, and where the
  artifact is. Everything else lives in the HTML you already opened.
- The grade takes several minutes. Say so once, plainly, and run it as **one foreground
  command with a ten-minute timeout** on the tool call. Do not background it and poll,
  and do not let a default two-minute tool timeout kill it mid-run.
- If the artifact fails to render for a missing dependency, install it **into the grader
  directory** (`uv pip install --target "$ROOT/grader" "jsonschema>=4.18"`) —
  `sys.path` already looks there, so nothing fights the system Python's install policy.
- The semantic stage spawns its own isolated Claude process per section. If those come
  back "Not logged in", the host's CLI has no credentials the child can read: say so
  plainly, report the deterministic half honestly as the deterministic half, and do not
  present a partial grade as verified.

## The connect path (account needed)

Signup at **https://app.summation.com/signup** needs a browser and a credit card and is
the one step you cannot do — run `open https://app.summation.com/signup` for them rather
than pasting the link. Then use the plugin's own `signin` skill for sign-in, and follow
the connectors documentation from `https://docs.summation.com/llms.txt` before writing
any connector config. Declare the checklist the same way before you start.

### Scope the first piece of work — one, and they pick it

What to monitor, report on, or automate first is **their business decision, not yours**
— it is exactly the "fork in scope" you come back to a person for. Mine their files for
candidates, then offer **two or three, one line each with why it fits**, and ask which
one. If the host has a structured ask-the-user tool, use it for this choice; otherwise
one plain question. Then build **that one**, show it running, and offer the others
after.

Never bake specific deliverables into your declared checklist before they have chosen —
"stand up churn-by-plan, monthly-adds, and plan-mix monitors" presumes three things
nobody asked for. The checklist step says "stand up your first monitor (you pick
which)", and the pick happens when you get there.

### Signing them in

Sign-in is the `signin` skill's job — prefer it. If a shell login is needed instead, the
device-code flow needs a browser, and a sandboxed session may not be allowed to drive an
interactive flow at all. Do not fight it: hand them one command with the `!` prefix so
its output lands in the session, and say what it will ask for.

```
! SUMCLI_INTENT="<the goal in one line>" sumcli auth login
```

Ask once whether their organization is on a dedicated host rather than the default
`api.summation.com` — the wrong base URL signs them into a tenant holding none of their
data.

### Credentials: never ask for a paste

**Never ask someone to paste a password, key, or connection string into the
conversation.** It puts the secret in a transcript, in your context, and in a tool
argument. Every time:

1. Write them a template beside their work and name the fields —
   `./summation-connection.json`:
   `{"config":{"pg_host":"","pg_port":5432,"pg_db":"","pg_user":"","pg_sslmode":"require"},"secrets":{"pg_pass":""}}`
2. Say one line: *"Fill in the blanks and save it — I'll read it from there and delete
   it once the connection is up."*
3. Use it with `--config-file`. Never `cat` it, never echo a secret into a command
   argument, never put one in a flag value.
4. Delete it once `connections test` passes, and say that you did.

If the credential lives in Keychain or a password manager, prefer that: name the exact
item and have them fill the template from it.

## Never

- **Never open with an inventory of their files.** Listing their work back to them is
  not information — they wrote it.
- **Never use our vocabulary where a plain word exists.** Not "read replica" — *a copy
  of your database that's safe to read from*. Not "catalog the tables" — *tell Summation
  which tables to use*. This applies to the options you offer, where it slips in most.
- **Never front-load caveats.** No list of what needs a card, a browser, or is UI-only
  before they have chosen anything. Raise each at the moment it blocks you, in one clause.
- **Never make them choose something technical.** Decide it, do it, say it in one clause.
- **Never describe the state of their workspace as though it were a finding.** An empty
  workspace is what a new account looks like. Just do the next thing.
- **Never restate their own work back to them.**

## Always

- Read `FORMAT.md` before your first message on a chosen path and follow it exactly.
- Come back to the person only for a real decision: a credential, a browser step, a fork
  in scope. Everything between those is yours to carry.
