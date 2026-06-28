# GitHub Traffic Board

A **local**, single-file GitHub traffic dashboard. One stdlib-only Python script
pulls your repositories' traffic from the GitHub API and renders a single,
self-contained `report.html` — cumulative **and** per-repo charts, trend
analysis, referrers, preview thumbnails, six themes — that opens **fully
offline**.

```
python3 gh_traffic.py
```

No `pip install`, no dependencies, no build step, no telemetry, no account or
service beyond your own GitHub token.

![GitHub Traffic Board](preview.png)

> **▶ Live demo** (renders in your browser):
> **[full board](https://raw.githack.com/HANCORE-linux/GitHub-Traffic-Board/main/demo.html)** ·
> **[light mode](https://raw.githack.com/HANCORE-linux/GitHub-Traffic-Board/main/demo-light.html)**
> — fictional data, no token, no real data.
> *(These links go live the moment the repo is public. GitHub itself shows
> `.html` files as **source**, not as a page — so until then, download
> [`demo.html`](demo.html) and open it locally.)*

---

## Install

It's a single self-contained file — drop it into `~/gh-traffic/` and run it:

```bash
mkdir -p ~/gh-traffic && \
curl -fsSL https://raw.githubusercontent.com/HANCORE-linux/GitHub-Traffic-Board/main/gh_traffic.py \
     -o ~/gh-traffic/gh_traffic.py && \
python3 ~/gh-traffic/gh_traffic.py
```

The report and the cache land in that same `~/gh-traffic/` folder. **No
`chmod +x` needed** — it's run via `python3`. *(If you'd rather launch it as
`./gh_traffic.py`, run `chmod +x ~/gh-traffic/gh_traffic.py` once; the script
already carries a `#!/usr/bin/env python3` shebang.)*

---

## Two ways to run

On the first run (with no token configured) it asks:

```
  [F] full   — your repos' traffic · needs a GitHub token
  [l] light  — any user's public data · no token
  choose [F/l]:
```

- **Full** — the real product: 14-day **views / clones / referrers** for every
  repo you own, plus stars, watchers, open issues/PRs, last-updated and the
  issues/PRs *you* authored anywhere. Needs a fine-grained token (see below).
- **Light** (`--public <username>`) — works for **any** GitHub user with **no
  token at all**, but only public metadata (stars, open issues, language,
  last-updated, avatar, thumbnails). **No traffic** — GitHub keeps
  views/clones/referrers private to the repo owner, so they're simply blank.

---

## Security — read this first

The GitHub Traffic API is **not** a harmless read-only scope: it requires
push-level trust on the repo. So mint the **smallest possible** token:

1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens**.
2. **Repository access:** only the repos you want to see (or *All repositories*).
3. **Permissions:** `Repository permissions → Administration → Read-only` —
   this covers views, clones and referrers. *(Optionally add
   `Pull requests → Read` so the open-PR counts resolve; without it they simply
   show "?". `Metadata → Read` is granted automatically; `Commit statuses` is
   not needed.)*
4. Set an **expiration**.

<p align="center">
  <img src="docs/token-fine-grained.png" alt="Settings → Developer Settings → Fine-grained tokens" width="320"><br>
  <em>Settings → Developer Settings → Personal access tokens → <strong>Fine-grained tokens</strong></em>
</p>

<p align="center">
  <img src="docs/token-permissions.png" alt="Repository permissions → Administration → Read-only" width="660"><br>
  <em>Repository permissions → <strong>Administration → Read-only</strong> — the only permission needed</em>
</p>

*(A **classic** token would need the broad `repo` scope — full read/write to
**all** your private repos. Avoid it. Light mode needs no token at all.)*

How this tool treats the token:

- It lives **only in this Python process** and is sent **only** to
  `api.github.com`.
- It is **never written into `report.html`** — the report contains only
  aggregated numbers. *(Verify: `grep -iE 'ghp_|github_pat_|bearer' report.html`
  finds nothing.)*
- The report has **no auto-loaded external resources** — charts are inline SVG,
  preview images and the avatar are embedded base64, no CDN, no third-party JS.
  It opens **fully offline**. *(The only outbound links are click-through
  `github.com` links on the repo/issue/PR labels.)*
- By default the token is **prompted each run** and never persisted.

### Token input (priority order)

1. `GITHUB_TOKEN` environment variable, else
2. `~/.config/gh-traffic/token` (only if you opted in with `--save-token`,
   stored `chmod 600`), else
3. an interactive prompt (default — nothing is stored).

The token is the **one** thing kept outside the project folder — deliberately,
so a secret can't end up in a folder you share or commit. `token` is in
`.gitignore` either way.

---

## Features

- **Cumulative chart** of views & clones across the repos you select, plus a
  **per-repo chart** (one line per repo) with a dropdown to pick *all / none /
  individual* repos.
- **Trend analysis** — every series shows ▲/▼ % comparing the recent half of the
  window against the prior half (per-repo: views **and** clones, side by side).
- **Referrers** — top referring sites per repo and aggregated across the board.
- **Per-repo cards** — preview image, stars, watchers, open issues / PRs
  (click-through to GitHub), and "updated *N*d ago", all the same height.
- **Six themes** (switch live, top-left): `gruvbox`, `rose pine`, `everforest`
  (dark) · `gruvbox light`, `catppuccin latte`, `tokyo night light` (light).
- **Beyond 14 days** — daily counts are merged into a local history store so the
  charts grow past GitHub's rolling 14-day window when you run it regularly.
- **Preview thumbnails** — finds `preview.png` (or any top-level / `showcases/`
  image), downscales it, and embeds it base64 so the report stays offline.
- **Sort** by views / clones / stars / updated / name; **exclude forks** toggle.

---

## Flags

| Flag | Effect |
|------|--------|
| `--public [USER]` | **light mode**: public data for `USER` (no token, no traffic) |
| `--out PATH` | output file (default: `~/gh-traffic/report.html`) |
| `--no-open` | don't open a browser |
| `--no-history` | don't read/write the local history store (pure 14-day snapshot) |
| `--save-token` | save the entered token to `~/.config/gh-traffic/token` (0600) |
| `--repos a,b,c` | only these repo names |
| `--workers N` | parallel fetch workers (default: 8) |
| `--no-thumbs` | skip preview images (faster; all placeholders) |
| `--refresh-thumbs` | re-fetch preview images, ignoring the ETag cache |

---

## Where it stores data

The output and cache live in **one tidy folder in your home directory** —
nothing is written into the cloned repo, and it's always in the same findable place:

```
~/gh-traffic/report.html         ← the generated board (--out to change)
~/gh-traffic/cache/history.json  ← accumulated daily counts (beats the 14-day window)
~/gh-traffic/cache/thumbs/       ← downscaled preview images + ETags (re-used via HTTP 304)
~/.config/gh-traffic/token       ← only with --save-token (a secret, kept in XDG)
```

The **traffic numbers are fetched fresh on every run** — the board is always
current. The cache only (a) *accumulates* daily history to extend past 14 days,
and (b) caches preview images to avoid re-downloading them. Neither makes the
displayed numbers stale. `--no-history` / `--refresh-thumbs` opt out.

### Light mode & rate limits

Light mode uses the **unauthenticated** GitHub API, which is limited to **60
requests/hour**. A scan of many repos with thumbnails can hit that ceiling;
thumbnails are cached, so just re-run to fill the gaps.

---

## Beyond 14 days — daily accumulation (systemd)

GitHub only serves a rolling 14-day window. Ready-made user units in
`contrib/systemd/` run the tool headlessly once a day so the history store keeps
growing:

```bash
# 1. make the token available headlessly (no prompt in a timer):
python3 gh_traffic.py --save-token        # stored 0600 in ~/.config/gh-traffic/token

# 2. install + enable the user timer:
mkdir -p ~/.config/systemd/user
cp contrib/systemd/gh-traffic.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gh-traffic.timer
systemctl --user list-timers gh-traffic.timer   # check it's scheduled
```

The units assume the script is at `~/gh-traffic/gh_traffic.py` (the install
location above); edit the paths if you put it elsewhere.

---

## Demo

GitHub shows `.html` files as **source code**, never as a live page (it won't
run repo HTML). To see the demo *rendered*:

- **In your browser (once the repo is public):**
  [full board](https://raw.githack.com/HANCORE-linux/GitHub-Traffic-Board/main/demo.html)
  · [light mode](https://raw.githack.com/HANCORE-linux/GitHub-Traffic-Board/main/demo-light.html)
  — these [githack](https://raw.githack.com) links serve the raw file with the
  right content type so the browser renders it (needs a public repo).
- **A `github.io` URL instead:** enable Pages once — *Settings → Pages → Source:
  Deploy from a branch → `main` / `/ (root)`* — then it's at
  `https://hancore-linux.github.io/GitHub-Traffic-Board/demo.html`.
- **Offline / while private:** download [`demo.html`](demo.html) (or clone) and
  open it in a browser.

The demos are full boards built from fictional data with generated preview
images — no token, no network. Regenerate them with `python3 make_demo.py`.

---

## Requirements

- **Python 3.9+** — standard library only.
- **ImageMagick** (`magick` or `convert`) — *optional*, only for preview
  thumbnails. Without it, cards show monogram placeholders.

---

## License

MIT — see [`LICENSE`](LICENSE).
