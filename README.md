# Swipe.bg PS5 watcher

Checks <https://swipe.bg/konzoli> every 15 minutes and pushes a phone notification
the moment a PlayStation 5 appears in stock.

## One-time setup on your phone

1. Install the **ntfy** app — [iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy).
2. Tap **+** → subscribe to topic: `swipe-ps5-4aaf5f0e5e`
3. Verify it works:

   ```sh
   python3 ps5_watch.py --test
   ```

   You should get a "PS5 watcher is alive" push within a second or two.

The topic name is the only secret — anyone who knows it can read (and post to) your
alerts, so don't share it. Change it any time in `config.json` and re-subscribe.

## Files

| File | What it is |
|---|---|
| `ps5_watch.py` | The scraper. Python stdlib only, no dependencies. |
| `config.json` | Your ntfy topic. |
| `state.json` | Which PS5 listings you've already been told about. |
| `watch.log` | One line per check. |
| `~/Library/LaunchAgents/bg.swipe.ps5watch.plist` | The 15-minute schedule. |

## Commands

```sh
python3 ps5_watch.py           # one check (what the schedule runs)
python3 ps5_watch.py --list    # show everything in stock right now, notify nothing
python3 ps5_watch.py --test    # send a test push
python3 ps5_watch.py --reset   # forget seen listings; next match alerts again
tail -f watch.log              # watch it work
```

## Managing the schedule

```sh
launchctl unload ~/Library/LaunchAgents/bg.swipe.ps5watch.plist   # pause
launchctl load -w ~/Library/LaunchAgents/bg.swipe.ps5watch.plist  # resume
launchctl list | grep ps5watch                                    # is it registered?
```

It only runs while the Mac is awake. After sleep, launchd fires the missed check
promptly on wake, so the worst case is "you hear about it when you open the lid".

## How it decides

Each product card on `/konzoli` is parsed for title, subtitle, condition and price.
A card counts as a hit when its title or subtitle matches `playstation 5` or `ps5`
(`MATCH` in `ps5_watch.py` — edit it to narrow, e.g. to disk editions only).

You get **one** push per listing URL. A listing that sells out and later returns
alerts again, because `state.json` only remembers what is currently in stock.

If a push fails to send, nothing is marked as seen, so the next run retries it.
If the page ever parses to zero listings, the run logs a warning and changes
nothing rather than assuming the shop is empty — that's the signal that swipe.bg
changed its HTML and the `CARD` regex needs updating.
