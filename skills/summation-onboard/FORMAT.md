# How every message to the person should look

This is the output template for the summation-onboard skill. The benchmark is a
document, not a terminal dump: a person skimming your message should get the point
from the bold lines alone.

## Structure

- **Bold the step names.** One bold span per step or section: `**Grading your report**`,
  `**3 of 4 — running the grade**`. Never a message with no bold structure.
- **Short paragraphs.** No paragraph over five lines. If a paragraph wants to be
  longer, it is a list.
- **Lists for options and findings.** Two to four items, one line each: what it is,
  what it produces, what it costs them.
- **At most one code block per message,** and only when the person needs to see the
  exact command or value. Your commands run through tools; do not echo them back
  as code blocks too.

## The setup receipt

Print it the first time **immediately after they choose a path** — rows for what is
already in place (the plugin, its skills, sign-in state if any). Then reprint it,
grown, as each later milestone lands: an install step, sign-in, the data connection
testing green. The person watches rows accumulate as milestones land.

| | What | Detail |
|---|---|---|
| ✓ | Summation plugin | `summation@summationai` v1.1.1 |
| ✓ | Skills | 16 installed with it — onboarding, connect, query, report, validate… |
| ✓ | Signed in | their@email · workspace **name** |
| ✓ | Live database | `connection-name` · connection test **green** · N tables attached: names |

Rules:

- **Verified rows only.** Every ✓ is backed by a command you just ran — `plugin list`
  for the plugin and skills, `whoami` for sign-in, the connection test plus the attach
  list for the database. A row you cannot evidence does not appear.
- Rows appear only for what this session actually did. A grade-only session shows the
  rows it earned, never a padded list.
- Versions and counts are read from the command output, never assumed.

## Progress

- Declare the numbered checklist before the first command.
- One line when a step starts, one line when it lands: what it produced, then what
  is next. No narration between those two lines.
- Close with exactly `N of N steps complete` when the declared list is done.

## Closing message after a deliverable

- The verdict first, in one bolded line.
- Two or three findings maximum, one line each, biggest first.
- Where the artifact is, and that you already opened it.
- Under 1200 characters, always — count them if you are close. The detail is in the
  artifact, not the terminal.

## Never

- Never open with an inventory of their files.
- Never front-load caveats; state a limitation at the moment it matters.
- Never use jargon without a plain gloss: read replica, SSL mode, dialect,
  catalog the tables, schema prefix.
- Never tell them to open something you could open for them.
