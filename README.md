# PhD watch

Checks the boards that carry funded PhD ads in media and communication, keeps a
record of everything it has already shown you, and reports only what is new.
Runs itself every weekday morning on GitHub Actions, commits the result to the
repo, and emails you the same digest.

## Files

```
phd_watch.py                    the watcher
sources.yml                     which boards, which keywords
requirements.txt                dependencies
.github/workflows/phd-watch.yml the daily schedule
seen.json                       created on first run, the memory
digests/YYYY-MM-DD.md           created on days with new ads
```

## Setup

**1. Make a private repo** on GitHub called `phd-watch`. Drop these files in,
putting `phd-watch.yml` at `.github/workflows/phd-watch.yml`.

**2. Set up the email sender.** With Gmail you need an app password, not your
normal one. Google Account, Security, 2-Step Verification, App passwords.
Generate one and copy the 16 characters.

**3. Add repo secrets.** Settings, Secrets and variables, Actions, New
repository secret. Five of them:

| Secret | Value |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | your Gmail address |
| `SMTP_PASS` | the app password from step 2 |
| `MAIL_TO` | where the digest should land |

**4. Seed it.** Actions tab, PhD watch, Run workflow, tick the seed box. This
records every ad currently live as already seen, so your first real digest is
new ads only rather than the whole board.

**5. Wait a day.** It runs at 06:15 UTC on weekdays. You can trigger it by hand
any time from the Actions tab.

## Running it locally

```bash
pip install -r requirements.txt
python phd_watch.py --dry-run
```

`--dry-run` prints what it found and writes nothing, which is the right way to
test a change to `sources.yml`.

## Adding a board

Three fields in `sources.yml`:

```yaml
- name: University of Southern Denmark
  url: <the vacancy list page>
  link_pattern: <a URL fragment only job ads contain>
  filter: true
```

To find `link_pattern`, open the listing page, right-click a job title, copy
the link, and look at what the job URLs have in common that the nav links do
not. Usually a path segment like `/job/` or `/ad/` or `/vacancy/`. It is a
regex, so escape the dots.

Set `filter: false` when the URL is already narrowed to your field by the site
itself, as with the first Academic Positions entry. Then every ad on that page
counts, no keyword test.

## Two things it will not do

**Sites that build their listings in JavaScript return nothing.** The script
reads the HTML as served. Jobbnorge and some university boards may come back
empty. When a board fails or returns zero every day, that is the reason, and
the fix is either an RSS feed if the site has one or the site's own email
alert. Do not fight it with more code.

**It does not judge fit.** It tells you what is new, not what is worth your
time. That part is still a conversation.

## Belt and braces

Keep the native alerts on as well. They catch ads that never reach an
aggregator: Academic Positions daily alert filtered to PhD and media and
communication studies, an AcademicTransfer saved search, EURAXESS, and the
NordMedia Network newsletter. The script is for boards with no alert worth
having, and for the deduplication the alerts do not give you.
