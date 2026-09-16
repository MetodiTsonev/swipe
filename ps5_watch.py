#!/usr/bin/env python3
"""Watch https://swipe.bg/konzoli for PlayStation 5 listings and push an alert via ntfy.sh.

Usage:
    ./ps5_watch.py            # one check (this is what launchd runs every 15 min)
    ./ps5_watch.py --list     # print everything currently in stock, notify nothing
    ./ps5_watch.py --test     # send a test push so you can confirm your phone gets it
    ./ps5_watch.py --reset    # forget what was already seen (next match alerts again)
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")
STATE_FILE = os.path.join(HERE, "state.json")
LOG_FILE = os.path.join(HERE, "watch.log")

URL = "https://swipe.bg/konzoli?show=96&sort=default"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# A listing counts as a hit if its title/subtitle matches this.
MATCH = re.compile(r"(?i)playstation\s*5|\bps5\b")

CARD = re.compile(r'<a href="(https://swipe\.bg/[^"]+)" class="pcard(.*?)</a>', re.S)


def log(msg):
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    cfg = {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    # Env wins over the file, so CI can inject the topic as an encrypted secret
    # and no config.json needs to exist in the repo.
    for env_key, cfg_key in (("NTFY_TOPIC", "ntfy_topic"), ("NTFY_SERVER", "ntfy_server")):
        if os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]
    if not cfg.get("ntfy_topic"):
        log("ERROR: no ntfy topic configured (set NTFY_TOPIC or create config.json)")
        sys.exit(2)
    return cfg


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"seen": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# Build our own opener with an empty ProxyHandler. The default opener asks macOS
# SystemConfiguration for proxy settings, which can hang indefinitely when the
# process is spawned by launchd rather than from a terminal session.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
    })
    with OPENER.open(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def text(pattern, blob):
    m = re.search(pattern, blob, re.S)
    return unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def parse(html):
    items = []
    for url, body in CARD.findall(html):
        items.append({
            "url": url,
            "title": text(r'p3-title">(.*?)</span>', body),
            "sub": text(r'p3-sub">(.*?)</span>', body),
            "price": text(r'p3-price[^"]*">(.*?)</span>', body),
            "condition": text(r'p3c-cond">(.*?)</span>', body),
        })
    return items


def describe(item):
    bits = [item["title"]]
    for key in ("sub", "condition", "price"):
        if item[key]:
            bits.append(item[key])
    return " · ".join(bits)


def push(cfg, title, message, click=None, priority="default", tags="video_game"):
    topic = cfg["ntfy_topic"]
    server = cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/")
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
        "Tags": tags,
    }
    if click:
        headers["Click"] = click
    req = urllib.request.Request("%s/%s" % (server, urllib.parse.quote(topic)),
                                 data=message.encode("utf-8"), headers=headers)
    with OPENER.open(req, timeout=30) as resp:
        resp.read()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg = load_config()

    if arg == "--reset":
        save_state({"seen": []})
        log("state reset")
        return 0

    if arg == "--test":
        push(cfg, "PS5 watcher is alive",
             "Test push from ps5_watch.py. If you see this, alerts will reach you.",
             click="https://swipe.bg/konzoli", tags="white_check_mark")
        # Never log the topic itself - it is the shared secret, and CI logs are public.
        log("test push sent")
        return 0

    try:
        html = fetch(URL)
    except (urllib.error.URLError, OSError) as exc:
        log("FETCH FAILED: %s" % exc)
        return 1

    items = parse(html)
    if not items:
        log("WARNING: parsed 0 listings - the page layout may have changed")
        return 1

    hits = [i for i in items if MATCH.search(i["title"] + " " + i["sub"])]

    if arg == "--list":
        log("%d listing(s) in stock:" % len(items))
        for i in items:
            print("  %s %s" % ("[PS5]" if i in hits else "     ", describe(i)))
            print("        %s" % i["url"])
        return 0

    state = load_state()
    seen = set(state.get("seen", []))
    current = {i["url"] for i in hits}
    new = [i for i in hits if i["url"] not in seen]

    if new:
        lines = [describe(i) for i in new]
        title = ("PS5 in stock at Swipe!" if len(new) == 1
                 else "%d PS5 listings at Swipe!" % len(new))
        try:
            push(cfg, title, "\n".join(lines),
                 click=new[0]["url"] if len(new) == 1 else "https://swipe.bg/konzoli",
                 priority="urgent")
        except (urllib.error.URLError, OSError) as exc:
            # Don't record these as seen, so the next run retries the alert.
            log("PUSH FAILED (%s) for: %s" % (exc, " | ".join(lines)))
            return 1
        log("ALERT sent for %d new PS5 listing(s): %s" % (len(new), " | ".join(lines)))
    else:
        log("no new PS5 (%d listings in stock, %d PS5 already known)" % (len(items), len(hits)))

    # Only remember what is still listed, so a sold-out-then-restocked PS5 alerts again.
    # Deliberately nothing volatile (no timestamp) in here: under GitHub Actions this
    # file is committed back to the repo, and it should only change when the PS5 set
    # does. Timestamps and counts belong in watch.log.
    save_state({"seen": sorted(current)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
