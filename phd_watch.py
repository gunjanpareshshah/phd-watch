#!/usr/bin/env python3
"""
phd_watch.py - daily watcher for funded PhD ads in media and communication.

Fetches each board listed in sources.yml, pulls out the job links, filters them
on keywords, drops anything already recorded in seen.json, and reports only
what is genuinely new. Output goes to digests/YYYY-MM-DD.md and, if SMTP
environment variables are set, to email.

Usage:
    python phd_watch.py                 # normal daily run
    python phd_watch.py --dry-run       # show results, write nothing, send nothing
    python phd_watch.py --seed          # record everything currently live as "seen"
    python phd_watch.py --always-email  # email even when there is nothing new
"""

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "sources.yml"
SEEN_PATH = ROOT / "seen.json"
DIGEST_DIR = ROOT / "digests"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en",
}
TIMEOUT = 30


# ---------------------------------------------------------------- config / state

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg.setdefault("include_keywords", [])
    cfg.setdefault("exclude_keywords", [])
    cfg.setdefault("sources", [])
    return cfg


def load_seen():
    if not SEEN_PATH.exists():
        return {}
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        print("seen.json is unreadable, starting from empty", file=sys.stderr)
        return {}


def save_seen(seen):
    with open(SEEN_PATH, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------- scraping

def canonical(url):
    """Dedupe key: scheme, host and path only, so tracking params do not
    make the same ad look new tomorrow."""
    parts = urlparse(url)
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc.lower()}{path}"


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def clean_title(text, limit=180):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def extract(source, html):
    """Pull candidate ads out of one listing page.

    Each source in sources.yml gives a `link_pattern` regex that job-ad URLs on
    that site match. Anything matching is treated as an ad; the anchor text is
    the title.
    """
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(source["link_pattern"])
    base = source["url"]
    found = {}

    for anchor in soup.find_all("a", href=True):
        href = urljoin(base, anchor["href"])
        if not pattern.search(href):
            continue
        title = clean_title(anchor.get_text(" ", strip=True))
        if len(title) < 12:
            continue  # image links, "Apply here", pagination chrome
        key = canonical(href)
        # Keep the longest anchor text seen for a URL; listings often link the
        # same ad from a thumbnail and from the headline.
        if key not in found or len(title) > len(found[key]["title"]):
            found[key] = {"url": href, "title": title, "source": source["name"]}

    return list(found.values())


def keep(item, source, include, exclude):
    haystack = item["title"].lower()

    for word in exclude:
        if word.lower() in haystack:
            return False

    # Sources that are already filtered by the site itself (a field-specific
    # URL, say) can set filter: false and skip the keyword test.
    if not source.get("filter", True):
        return True

    if not include:
        return True
    return any(word.lower() in haystack for word in include)


def collect(cfg):
    include = cfg["include_keywords"]
    exclude = cfg["exclude_keywords"]
    items, errors = [], []

    for source in cfg["sources"]:
        if not source.get("enabled", True):
            continue
        try:
            html = fetch(source["url"])
        except Exception as exc:  # noqa: BLE001 - one bad board must not kill the run
            errors.append(f"{source['name']}: {exc}")
            continue

        hits = [i for i in extract(source, html) if keep(i, source, include, exclude)]
        print(f"{source['name']}: {len(hits)} matching ads live")
        items.extend(hits)

    # Same ad can surface on two boards; first one wins.
    deduped = {}
    for item in items:
        deduped.setdefault(canonical(item["url"]), item)
    return list(deduped.values()), errors


# ---------------------------------------------------------------- output

def build_digest(new_items, live_count, errors, today):
    lines = [f"# PhD watch, {today.isoformat()}", ""]

    if new_items:
        lines.append(f"**{len(new_items)} new since last run** ({live_count} ads live in total).")
        lines.append("")
        by_source = {}
        for item in new_items:
            by_source.setdefault(item["source"], []).append(item)
        for source_name in sorted(by_source):
            lines.append(f"## {source_name}")
            lines.append("")
            for item in sorted(by_source[source_name], key=lambda i: i["title"]):
                lines.append(f"- [{item['title']}]({item['url']})")
            lines.append("")
    else:
        lines.append(f"No new ads. {live_count} still live, all seen before.")
        lines.append("")

    if errors:
        lines.append("## Boards that failed")
        lines.append("")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


def write_digest(text, today):
    DIGEST_DIR.mkdir(exist_ok=True)
    path = DIGEST_DIR / f"{today.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    return path


def send_email(subject, body):
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    to_addr = os.environ.get("MAIL_TO")
    port = int(os.environ.get("SMTP_PORT", "465"))

    if not all([host, user, password, to_addr]):
        print("SMTP variables not set, skipping email")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("MAIL_FROM", user)
    msg["To"] = to_addr
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context) as server:
        server.login(user, password)
        server.send_message(msg)
    print(f"Emailed {to_addr}")
    return True


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    parser.add_argument("--seed", action="store_true", help="mark everything live as already seen")
    parser.add_argument("--always-email", action="store_true", help="email even with nothing new")
    args = parser.parse_args()

    cfg = load_config()
    seen = load_seen()
    today = date.today()

    live, errors = collect(cfg)
    print(f"{len(live)} ads live across all boards, {len(seen)} already on record")

    if args.seed:
        for item in live:
            seen[canonical(item["url"])] = {
                "title": item["title"],
                "source": item["source"],
                "first_seen": today.isoformat(),
            }
        save_seen(seen)
        print(f"Seeded {len(live)} ads. Tomorrow's run reports only what appears after today.")
        return 0

    new_items = [i for i in live if canonical(i["url"]) not in seen]
    digest = build_digest(new_items, len(live), errors, today)
    print()
    print(digest)

    if args.dry_run:
        print("(dry run, nothing written or sent)")
        return 0

    if new_items or args.always_email:
        write_digest(digest, today)

    if new_items:
        subject = f"PhD watch: {len(new_items)} new"
    else:
        subject = "PhD watch: nothing new"

    if new_items or args.always_email:
        try:
            send_email(subject, digest)
        except Exception as exc:  # noqa: BLE001 - a mail failure must not lose the state write
            print(f"Email failed: {exc}", file=sys.stderr)

    for item in new_items:
        seen[canonical(item["url"])] = {
            "title": item["title"],
            "source": item["source"],
            "first_seen": today.isoformat(),
        }
    save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
