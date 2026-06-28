#!/usr/bin/env python3
"""Generate demo.html for gh-traffic — fictional numbers + generated preview images,
no token and no network. Run: python3 make_demo.py  (writes demo.html next to it)."""
import importlib.util
import base64
import subprocess
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("ght", HERE / "gh_traffic.py")
ght = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ght)

random.seed(42)  # deterministic demo
MAGICK = ght.MAGICK
NOW = datetime.now(timezone.utc)


def gen_image(text, c1, c2, w=480, h=270, pt=34):
    if not MAGICK:
        return None
    out = subprocess.run(
        [MAGICK, "-size", f"{w}x{h}", f"gradient:{c1}-{c2}", "-gravity", "center",
         "-pointsize", str(pt), "-fill", "white", "-annotate", "0", text,
         "-quality", "80", "webp:-"],
        capture_output=True).stdout
    return "data:image/webp;base64," + base64.b64encode(out).decode("ascii") if out else None


def daily_series(n, base, trend, spike_at=None):
    """n days ending today; linear trend + noise; optional spike."""
    vals = []
    for i in range(n):
        v = base + int(trend * i) + random.randint(-max(1, base // 3), max(1, base // 3))
        if spike_at is not None and i == spike_at:
            v *= 3
        vals.append(max(0, v))
    days = [{"date": (NOW.date() - timedelta(days=n - 1 - i)).isoformat(),
             "count": vals[i], "uniques": max(1, vals[i] * 2 // 3)} for i in range(n)]
    return days, sum(vals)


def make_repo(name, c1, c2, stars, iss, prs, days_ago, watchers,
              vbase, vtrend, cbase, refs, spike=False, fork=False):
    n = 16
    vdaily, vtot = daily_series(n, vbase, vtrend, spike_at=n - 3 if spike else None)
    cdaily, ctot = daily_series(n, cbase, 0)
    return {
        "name": name, "private": False, "fork": fork,
        "stars": stars, "open_issues_total": iss + prs, "open_prs": prs,
        "pushed_at": (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "watchers": watchers, "thumb": gen_image(name, c1, c2),
        "views": {"count": vtot, "uniques": vtot * 2 // 3, "daily": vdaily},
        "clones": {"count": ctot, "uniques": ctot * 2 // 3, "daily": cdaily},
        "referrers": refs,
    }


def ref(**kw):
    return [{"referrer": r, "count": c, "uniques": max(1, c * 2 // 3)} for r, c in kw.items() if c]


# (name, grad1, grad2, stars, issues, prs, days_ago, watchers, view_base, view_trend, clone_base, referrers, spike, fork)
SPEC = [
    ("aurora-bar",         "#1e3a8a", "#9333ea", 412, 5, 2, 1, 38,  60,  6, 14,
        ref(**{"github.com": 820, "www.google.com": 240, "news.ycombinator.com": 190, "reddit.com": 95}), True, False),
    ("nova-theme",         "#0f766e", "#22d3ee", 268, 3, 1, 2, 21,  40,  4,  9,
        ref(**{"github.com": 510, "duckduckgo.com": 88, "reddit.com": 64}), False, False),
    ("pixel-forge",        "#9a3412", "#f59e0b", 153, 8, 0, 6, 14,  28, -2,  7,
        ref(**{"github.com": 300, "www.google.com": 60}), False, False),
    ("quartz-ui",          "#3730a3", "#60a5fa", 96,  2, 3, 0, 11,  22,  3,  5,
        ref(**{"github.com": 210, "t.co": 44, "bing.com": 19}), False, False),
    ("stellar-cli",        "#155e75", "#34d399", 740, 12, 4, 3, 64, 95,  9, 20,
        ref(**{"github.com": 1500, "news.ycombinator.com": 420, "www.google.com": 380, "reddit.com": 160}), True, False),
    ("lumen-dots",         "#581c87", "#ec4899", 58,  1, 0, 11, 6,  15,  1,  4,
        ref(**{"github.com": 130}), False, False),
    ("cobalt-shell",       "#1e40af", "#38bdf8", 204, 4, 2, 4, 18,  35, -3,  8,
        ref(**{"github.com": 360, "reddit.com": 70, "duckduckgo.com": 33}), False, False),
    ("ember-icons",        "#7c2d12", "#fb923c", 121, 0, 1, 8, 9,   19,  2,  6,
        ref(**{"github.com": 240, "www.google.com": 52}), False, False),
    ("mirage-wallpapers",  "#134e4a", "#5eead4", 333, 2, 0, 5, 27,  44,  5, 11,
        ref(**{"github.com": 600, "www.google.com": 140, "reddit.com": 88}), False, False),
    ("zephyr-fetch",       "#312e81", "#818cf8", 47,  3, 1, 14, 5,  12,  0,  3,
        ref(**{"github.com": 95}), False, False),
    ("onyx-grub-theme",    "#374151", "#9ca3af", 89,  1, 0, 9, 8,   17,  1,  5,
        ref(**{"github.com": 180, "bing.com": 24}), False, False),
    ("flux-launcher",      "#155e63", "#2dd4bf", 31,  0, 0, 20, 3,  9,  -1,  2,
        ref(), False, True),
]


def to_light(repos):
    """What the light-mode collector would produce: public metadata + thumbnails,
    but no traffic (private) and no per-repo PR/watcher calls."""
    out = []
    for r in repos:
        lr = dict(r)
        lr["views"] = {"count": 0, "uniques": 0, "daily": []}
        lr["clones"] = {"count": 0, "uniques": 0, "daily": []}
        lr["referrers"] = []
        lr["open_prs"] = None
        lr["watchers"] = None
        out.append(lr)
    return out


def main():
    repos = [make_repo(*s) for s in SPEC]
    base = {
        "user": "demo-user",
        "avatar": gen_image("DU", "#3730a3", "#06b6d4", w=96, h=96, pt=30),
        "followers": 342,
        "authored_issues": 7,
        "authored_prs": 3,
        "light": False,
        "window_days": 14,
        "skipped": [],
    }
    full = {**base, "repos": repos,
            "generated": NOW.strftime("%Y-%m-%d %H:%M UTC") + " (DEMO — fictional data)"}
    ght.render(full, HERE / "demo.html")
    light = {**base, "light": True, "repos": to_light(repos),
             "generated": NOW.strftime("%Y-%m-%d %H:%M UTC") + " (DEMO — light mode, fictional data)"}
    ght.render(light, HERE / "demo-light.html")
    for f in ("demo.html", "demo-light.html"):
        p = HERE / f
        print(f"wrote {p}  ({p.stat().st_size // 1024} KB)")
    if not MAGICK:
        print("  note: ImageMagick not found — preview images are placeholders.")


if __name__ == "__main__":
    main()
