#!/usr/bin/env python3
"""gh-traffic — lightweight, local GitHub traffic dashboard.

Pulls 14-day traffic (views, clones, referrers) for every repo
you own and renders a single, self-contained HTML report in the cliamp
terminal aesthetic. Cumulative across all repos plus a per-repo chart, trend
analysis, and per-repo cards with referring sites, stars and issues/PRs.

Security model (deliberate):
  - The token lives ONLY in this process and is sent ONLY to api.github.com.
  - The token is NEVER written into report.html — only aggregated numbers are.
  - stdlib only: no requests/rich, no pip install, no telemetry, no CDN.
  - Charts are inline SVG drawn by vanilla JS, so the report works fully offline.

Use a fine-grained PAT, scoped to the repos you want, "Administration: read",
with an expiry. See README.md.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com"
DATA_DIR = Path.home() / "gh-traffic"               # report + cache live in one tidy home folder (not the cloned repo)
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gh-traffic"
CACHE_DIR = DATA_DIR / "cache"
TOKEN_FILE = CONFIG_DIR / "token"                    # the token (a secret) stays in XDG, NOT the project folder
HISTORY_FILE = CACHE_DIR / "history.json"
THUMB_DIR = CACHE_DIR / "thumbs"
MAGICK = shutil.which("magick") or shutil.which("convert")  # optional image downscaler


# ───────────────────────────── token handling ─────────────────────────────
def clean_token(t: str) -> str:
    """Strip terminal paste artifacts (bracketed-paste / ANSI escape / control
    chars) that some terminals inject into a hidden getpass field, so a mangled
    paste still yields the real token. GitHub tokens are [A-Za-z0-9_] only, so
    this never harms a clean token."""
    import re
    t = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", t)  # CSI seqs incl bracketed-paste \x1b[200~ / [201~
    t = re.sub(r"\x1b.", "", t)                        # other ESC-x escapes, e.g. \x1bv
    t = re.sub(r"[\x00-\x1f\x7f]", "", t)              # stray control chars
    return t.strip()


def _token_available() -> bool:
    """A token can be resolved non-interactively (env or saved file)."""
    return bool(clean_token(os.environ.get("GITHUB_TOKEN", ""))) or TOKEN_FILE.exists()


def load_token(save: bool) -> tuple[str, str]:
    """Resolve the token: $GITHUB_TOKEN > config file > interactive prompt.

    Returns (token, source). The source is reported so a silently auto-picked
    stale token can't masquerade as "your input". The token never lands in the
    project dir; --save-token stows it in the XDG config dir with 0600 perms.
    """
    token = clean_token(os.environ.get("GITHUB_TOKEN", ""))
    if token:
        return token, "env"
    if TOKEN_FILE.exists():
        token = clean_token(TOKEN_FILE.read_text(encoding="utf-8"))
        if token:
            return token, "file"
    raw = getpass.getpass("GitHub fine-grained PAT (Administration: read): ")
    token = clean_token(raw)
    if not token:
        sys.exit("No token provided. Aborting.")
    if token != raw.strip():
        print("Note: stripped terminal paste artifacts (escape/control chars) from the pasted token.")
    if save:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Create with 0600 directly (no world-readable window), and enforce 0600
        # even if the file already existed with looser perms.
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token + "\n")
        os.chmod(TOKEN_FILE, 0o600)
        print(f"Token saved to {TOKEN_FILE} (chmod 600).")
    return token, "prompt"


def token_fingerprint(tok: str) -> str:
    """Non-secret description of the received token — diagnoses paste corruption
    (bracketed-paste escapes, control chars, truncation) WITHOUT printing it."""
    import re
    prefixes = {"github_pat_": "fine-grained", "ghp_": "classic", "gho_": "oauth",
                "ghs_": "app", "ghr_": "refresh"}
    kind = next((v for p, v in prefixes.items() if tok.startswith(p)), f"unknown(prefix={tok[:4]!r})")
    issues = []
    if any(c.isspace() for c in tok):
        issues.append("whitespace-inside")
    if any(ord(c) < 32 or ord(c) == 127 for c in tok):
        issues.append("control-chars")
    if "\x1b" in tok or "200~" in tok or "201~" in tok:
        issues.append("bracketed-paste-escapes")
    if not tok.isascii():
        issues.append("non-ascii")
    if not re.fullmatch(r"[A-Za-z0-9_]*", tok):
        issues.append("unexpected-chars")
    tail = "looks well-formed" if not issues else "ISSUES → " + ", ".join(issues)
    return f"length={len(tok)}, type={kind}, {tail}"


# ───────────────────────────── github api ─────────────────────────────────
class GitHub:
    def __init__(self, token: str | None = None):
        # no token → the public, unauthenticated API (light mode; 60 req/h limit)
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gh-traffic (local; stdlib)",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, params: dict | None = None) -> tuple[int, object]:
        """Return (status, parsed_json). Network errors surface as the status."""
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {"message": body[:200]}
            return e.code, payload
        except urllib.error.URLError as e:
            return 0, {"message": f"network error: {e.reason}"}

    def whoami(self, source: str = "prompt") -> tuple[str, str, int]:
        status, data = self.get("/user")
        if status == 401:
            where = {"env": "$GITHUB_TOKEN", "file": str(TOKEN_FILE), "prompt": "your input"}.get(source, source)
            hint = {
                "env": "\n→ a stale env token was used, not a prompt. Clear it (fish: `set -e GITHUB_TOKEN`; bash: `unset GITHUB_TOKEN`) and re-run.",
                "file": f"\n→ a stale saved token was used, not a prompt. `rm {TOKEN_FILE}` and re-run.",
            }.get(source, "")
            raw = self._headers.get("Authorization", "Bearer ").removeprefix("Bearer ")
            sys.exit(f"401 Unauthorized — the token from {where} is invalid or expired."
                     f"\n  received: {token_fingerprint(raw)}{hint}")
        if status != 200 or not isinstance(data, dict) or "login" not in data:
            sys.exit(f"Could not detect user (HTTP {status}): {data}")
        return data["login"], data.get("avatar_url", ""), data.get("followers", 0)

    def authored_counts(self, login: str) -> tuple[int | None, int | None]:
        """Open issues & PRs the user AUTHORED anywhere (Search API), independent
        of repo ownership — so a PR you opened in someone else's repo counts here
        but not in the per-repo totals. Returns (issues, prs); a value is None if
        search is unavailable (e.g. a fine-grained token without search access)."""
        out = []
        for typ in ("issue", "pr"):
            st, data = self.get("/search/issues", {"q": f"author:{login} state:open type:{typ}", "per_page": 1})
            out.append(data.get("total_count") if (st == 200 and isinstance(data, dict)) else None)
        return out[0], out[1]

    def owned_repos(self) -> list[dict]:
        """All repos the user owns (incl. private), paginated."""
        repos: list[dict] = []
        page = 1
        while True:
            status, data = self.get(
                "/user/repos",
                {"affiliation": "owner", "per_page": 100, "page": page, "sort": "full_name"},
            )
            if status != 200 or not isinstance(data, list):
                sys.exit(f"Could not list repos (HTTP {status}): {data}")
            if not data:
                break
            repos.extend(data)
            if len(data) < 100:
                break
            page += 1
        return repos

    def public_user(self, username: str) -> tuple[str, str, int]:
        """Public profile (no token needed): (login, avatar_url, followers)."""
        status, data = self.get(f"/users/{username}")
        if status == 404:
            sys.exit(f"GitHub user '{username}' not found.")
        if status == 403:
            sys.exit("GitHub rate limit hit (unauthenticated = 60 req/h). Wait an hour, or use the full token mode.")
        if status != 200 or not isinstance(data, dict) or "login" not in data:
            sys.exit(f"Could not load user '{username}' (HTTP {status}): {data}")
        return data["login"], data.get("avatar_url", ""), data.get("followers", 0)

    def public_repos(self, username: str) -> list[dict]:
        """A user's PUBLIC repos (no token), newest-pushed first, paginated. Stops
        gracefully on the unauthenticated 60 req/h rate limit."""
        repos: list[dict] = []
        page = 1
        while True:
            status, data = self.get(
                f"/users/{username}/repos",
                {"type": "owner", "per_page": 100, "page": page, "sort": "pushed"},
            )
            if status == 403:
                print("  ! rate limit hit while listing repos — showing what loaded.")
                break
            if status != 200 or not isinstance(data, list) or not data:
                break
            repos.extend(data)
            if len(data) < 100:
                break
            page += 1
        return repos

    def traffic(self, owner: str, repo: str) -> dict:
        """Fetch the traffic for one repo. views/clones are required (raise on
        no-access → the repo is skipped); referrers is best-effort so a transient
        referrer hiccup can't drop a repo whose core traffic loaded fine."""
        def need(path):
            status, data = self.get(path)
            if status != 200:
                msg = data.get("message", "") if isinstance(data, dict) else str(data)
                raise PermissionError(f"HTTP {status}: {msg}")
            return data

        def best_effort(path):
            status, data = self.get(path)
            return data if status == 200 and isinstance(data, list) else []

        base = f"/repos/{owner}/{repo}/traffic"
        views = need(f"{base}/views")
        clones = need(f"{base}/clones")
        referrers = best_effort(f"{base}/popular/referrers")
        return {"views": views, "clones": clones, "referrers": referrers}

    def open_pr_count(self, owner: str, repo: str):
        """Count open PRs (so issues = open_issues_count - PRs). None on failure.
        Caps at 100 open PRs (irrelevant for typical repos)."""
        status, data = self.get(f"/repos/{owner}/{repo}/pulls", {"state": "open", "per_page": 100})
        if status != 200 or not isinstance(data, list):
            return None
        return len(data)

    def get_raw(self, path: str, etag: str | None = None):
        """Fetch a file's RAW bytes via the contents endpoint (raw media type,
        works for files >1MB and private repos, follows the default branch).
        Returns (status, bytes|None, etag). 304 when If-None-Match still matches."""
        req = urllib.request.Request(API + path, headers={**self._headers, "Accept": "application/vnd.github.raw"})
        if etag:
            req.add_header("If-None-Match", etag)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read(), resp.headers.get("ETag")
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, None, etag
            return e.code, None, None
        except urllib.error.URLError:
            return 0, None, None

    def watchers(self, owner: str, repo: str):
        """Real watcher count (subscribers_count). Only the single-repo GET returns
        it — the list endpoint's 'watchers_count' is just a stars alias. Returns int
        or None."""
        status, data = self.get(f"/repos/{owner}/{repo}")
        if status != 200 or not isinstance(data, dict):
            return None
        return data.get("subscribers_count")


def day(ts: str) -> str:
    """'2026-06-27T00:00:00Z' -> '2026-06-27'."""
    return ts.split("T", 1)[0]


def _datauri(p: Path) -> str:
    return "data:image/webp;base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def fetch_avatar(url: str) -> str | None:
    """Fetch the user's GitHub avatar (small) as a base64 data-URI, or None.
    avatars.githubusercontent.com is public (no auth), embedded so the report
    stays offline."""
    if not url:
        return None
    small = url + ("&" if "?" in url else "?") + "s=96"
    try:
        req = urllib.request.Request(small, headers={"User-Agent": "gh-traffic"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ct = r.headers.get("Content-Type", "image/png")
            data = r.read()
        return f"data:{ct};base64," + base64.b64encode(data).decode("ascii")
    except Exception:
        return None


IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
SHOWCASE_DIRS = ("showcase", "showcases", "screenshots", "screenshot", "assets", "images", "img", "media", "docs")
NAME_PREF = ("preview", "screenshot", "banner", "showcase", "demo", "cover", "hero", "thumbnail")


def _pick_image(items: list) -> str | None:
    """Best image file (by name preference, then name) from a contents listing, or None."""
    imgs = [it for it in items if isinstance(it, dict) and it.get("type") == "file"
            and it.get("name", "").lower().endswith(IMG_EXT)]
    if not imgs:
        return None
    def rank(it):
        n = it["name"].lower()
        return next((i for i, p in enumerate(NAME_PREF) if p in n), len(NAME_PREF))
    imgs.sort(key=lambda it: (rank(it), it["name"].lower()))
    return imgs[0].get("path")


def discover_image(gh: GitHub, owner: str, repo: str) -> str | None:
    """A preview-image path when there's no preview.png: any top-level image, else
    one image from a single showcase-like folder. ONLY the first tree level — never
    recurses deeper."""
    st, root = gh.get(f"/repos/{owner}/{repo}/contents")
    if st != 200 or not isinstance(root, list):
        return None
    p = _pick_image(root)            # top-level image (preview.jpg, screenshot.png, …)
    if p:
        return p
    for it in root:                  # one level into the first showcase-like folder
        if isinstance(it, dict) and it.get("type") == "dir" and it.get("name", "").lower() in SHOWCASE_DIRS:
            st2, sub = gh.get(f"/repos/{owner}/{repo}/contents/{it['name']}")
            if st2 == 200 and isinstance(sub, list):
                p = _pick_image(sub)
                if p:
                    return p
    return None


def _thumb_from_path(gh, owner, repo, path, etag, webp, etagf, pathf):
    """Fetch one image path, downscale+cache to webp. Returns (datauri|None, status)."""
    status, data, new_etag = gh.get_raw(f"/repos/{owner}/{repo}/contents/{path}", etag)
    if status == 304 and webp.exists():
        return _datauri(webp), 304
    if status == 200 and data:
        src = THUMB_DIR / f"{repo}.src{Path(path).suffix.lower()}"
        src.write_bytes(data)
        try:
            subprocess.run([MAGICK, str(src), "-resize", "480x", "-quality", "78", str(webp)],
                           check=True, capture_output=True, timeout=60)
        except Exception:
            return None, 0
        finally:
            src.unlink(missing_ok=True)
        if new_etag:
            etagf.write_text(new_etag, encoding="utf-8")
        pathf.write_text(path, encoding="utf-8")
        return (_datauri(webp) if webp.exists() else None), 200
    return None, status


def fetch_thumb(gh: GitHub, owner: str, repo: str, refresh: bool) -> str | None:
    """Small base64 WebP of the repo's preview image, or None. Tries preview.png,
    else discovers a top-level / showcase-folder image (see discover_image). The
    found path + ETag are cached, so later runs send If-None-Match and reuse the
    downscaled thumb on 304 (no re-download). Keeps the report a single offline file."""
    if not MAGICK:
        return None
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    webp = THUMB_DIR / f"{repo}.webp"
    etagf = THUMB_DIR / f"{repo}.etag"
    pathf = THUMB_DIR / f"{repo}.path"
    cached = webp.exists() and not refresh
    # 1) the previously-found path (or preview.png by default), conditional on ETag
    path = pathf.read_text(encoding="utf-8").strip() if (cached and pathf.exists()) else "preview.png"
    etag = etagf.read_text(encoding="utf-8").strip() if (cached and etagf.exists()) else None
    uri, status = _thumb_from_path(gh, owner, repo, path, etag, webp, etagf, pathf)
    if status in (200, 304):
        return uri
    # 2) preview.png missing & nothing cached → discover an alternative image, once
    if not cached:
        disc = discover_image(gh, owner, repo)
        if disc and disc != path:
            uri, status = _thumb_from_path(gh, owner, repo, disc, None, webp, etagf, pathf)
            if status == 200:
                return uri
    # 3) transient error but a cached thumb exists
    if webp.exists():
        return _datauri(webp)
    return None


def collect(gh: GitHub, owner: str, repos: list[dict], workers: int,
            want_thumbs: bool = True, refresh_thumbs: bool = False) -> tuple[list[dict], list[dict]]:
    """Fan out traffic fetches (and per-repo preview thumbnails). Returns (collected, skipped)."""
    collected: list[dict] = []
    skipped: list[dict] = []

    def one(r: dict):
        # Fail-open per repo: a missing name, a no-access (403/404), or a single
        # malformed payload must skip that repo, never crash the whole run.
        name = r.get("name")
        if not name:
            return ("skip", {"name": "<unknown>", "reason": "repo missing name field"})
        try:
            t = gh.traffic(owner, name)
            oc = r.get("open_issues_count", 0)  # combined issues + PRs (free, from /user/repos)
            prs = gh.open_pr_count(owner, name) if oc > 0 else 0  # split only when there's something
            watch = gh.watchers(owner, name)
            thumb = None
            if want_thumbs:
                try:
                    thumb = fetch_thumb(gh, owner, name, refresh_thumbs)
                except Exception:
                    thumb = None  # a thumbnail problem must never drop the repo's traffic
            v, c = t["views"], t["clones"]
            return ("ok", {
                "name": name,
                "private": r.get("private", False),
                "fork": r.get("fork", False),
                "stars": r.get("stargazers_count", 0),
                "open_issues_total": oc,
                "open_prs": prs,
                "pushed_at": r.get("pushed_at") or "",
                "watchers": watch,
                "thumb": thumb,
                "views": {
                    "count": v.get("count", 0),
                    "uniques": v.get("uniques", 0),
                    "daily": [{"date": day(x["timestamp"]), "count": x["count"], "uniques": x["uniques"]}
                              for x in v.get("views", [])],
                },
                "clones": {
                    "count": c.get("count", 0),
                    "uniques": c.get("uniques", 0),
                    "daily": [{"date": day(x["timestamp"]), "count": x["count"], "uniques": x["uniques"]}
                              for x in c.get("clones", [])],
                },
                "referrers": [{"referrer": x["referrer"], "count": x["count"], "uniques": x["uniques"]}
                              for x in t["referrers"]],
            })
        except PermissionError as e:
            return ("skip", {"name": name, "reason": str(e)})
        except Exception as e:  # malformed payload, etc. — don't kill the run
            return ("skip", {"name": name, "reason": f"error: {e}"})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for kind, item in pool.map(one, repos):
            (collected if kind == "ok" else skipped).append(item)
    collected.sort(key=lambda r: r["views"]["count"], reverse=True)
    return collected, skipped


def collect_light(gh: GitHub, owner: str, repos: list[dict],
                  want_thumbs: bool = True, refresh_thumbs: bool = False) -> list[dict]:
    """Light mode: public metadata + thumbnails only. NO traffic (views/clones/
    referrers are private — unavailable without a token), and no per-repo extra
    calls (watchers / PR split) so a username scan stays under the 60 req/h limit."""
    def one(r: dict):
        name = r.get("name")
        if not name:
            return None
        thumb = None
        if want_thumbs:
            try:
                thumb = fetch_thumb(gh, owner, name, refresh_thumbs)
            except Exception:
                thumb = None
        return {
            "name": name,
            "private": False,
            "fork": r.get("fork", False),
            "stars": r.get("stargazers_count", 0),
            "open_issues_total": r.get("open_issues_count", 0),  # issues+PRs combined
            "open_prs": None,        # can't split without /pulls (a call per repo) → card shows '?'
            "pushed_at": r.get("pushed_at") or "",
            "watchers": None,        # needs a per-repo GET → skipped (rate limit)
            "thumb": thumb,
            "views": {"count": 0, "uniques": 0, "daily": []},
            "clones": {"count": 0, "uniques": 0, "daily": []},
            "referrers": [],
        }
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:   # gentle on the unauth limit
        for res in ex.map(one, repos):
            if res:
                out.append(res)
    out.sort(key=lambda r: r["stars"], reverse=True)
    return out


# ───────────────────────────── history (14-day workaround) ─────────────────
def merge_history(collected: list[dict]) -> dict:
    """Merge today's daily counts into a long-lived local store, deduped by date.

    GitHub only serves 14 days; running this regularly accumulates real history.
    Only `count` is mergeable (uniques can't be summed across days), so we keep
    counts here and read the authoritative 14-day uniques live.
    """
    try:
        store = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        store = {}
    for r in collected:
        slot = store.setdefault(r["name"], {"views": {}, "clones": {}})
        for kind in ("views", "clones"):
            for d in r[kind]["daily"]:
                slot[kind][d["date"]] = d["count"]  # last-writer-wins == latest fetch
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, HISTORY_FILE)  # atomic
    return store


def attach_history(collected: list[dict], store: dict) -> None:
    """Replace each repo's daily series with the merged (possibly >14d) series."""
    for r in collected:
        slot = store.get(r["name"], {})
        for kind in ("views", "clones"):
            series = sorted((slot.get(kind) or {}).items())
            r[kind]["history"] = [{"date": d, "count": c} for d, c in series]


# ───────────────────────────── html report ────────────────────────────────
def render(data: dict, out: Path) -> None:
    # Escape '<' so a crafted repo/referrer/path string can never break out of
    # the <script> block (e.g. "</script>"). < stays valid JSON-in-JS.
    blob = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    html = HTML_TEMPLATE.replace("/*__DATA__*/null", blob)
    out.write_text(html, encoding="utf-8")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>gh-traffic</title>
<style>
:root{
  --bg:#0c0d0f; --s0:#131415; --s1:#3c3836; --s2:#504945;
  --bd:#3c3836; --bdhi:#504945;
  --tx:#ebdbb2; --txhi:#fbf1c7; --txmax:#fbf1c7;
  --green:#b8bb26; --amber:#fabd2f; --cyan:#83a598; --red:#fb4934; --mut:#928374;
}
*{box-sizing:border-box}
body{
  margin:0; padding:0; background:var(--bg); color:var(--tx);
  font-family:"SF Mono","Cascadia Code","Fira Code","JetBrains Mono","IBM Plex Mono","Consolas","Liberation Mono",monospace;
  font-size:13px; line-height:1.5; letter-spacing:0;
  -webkit-font-smoothing:antialiased; -moz-osx-font-smoothing:grayscale; text-rendering:optimizeLegibility;
}
/* scanlines */
body::after{
  content:""; position:fixed; inset:0; pointer-events:none; z-index:9999;
  background:repeating-linear-gradient(to bottom,transparent 0,transparent 1px,#000 1px,#000 2px);
  opacity:0; mix-blend-mode:multiply;
}
.wrap{max-width:1040px; margin:0 auto; padding:28px 20px 80px}
a{color:var(--cyan); text-decoration:none}
a:hover{text-decoration:underline}
.muted{color:var(--mut)}
.tty{border:1px solid var(--bdhi); border-radius:8px; background:var(--s0); margin:0 0 22px; overflow:hidden}
.tty-head{
  display:flex; align-items:center; gap:8px; padding:8px 12px;
  background:linear-gradient(to bottom,var(--s1),var(--s0)); border-bottom:1px solid var(--bd);
  font-size:11px; color:var(--mut); letter-spacing:1px;
}
.swrow{display:flex; gap:3px; align-items:center}
.swrow .sw2{width:9px; height:9px; border-radius:2px}
.themebar{display:flex; gap:10px; align-items:center; margin:0 0 16px; font-size:11px; color:var(--mut)}
.tty-head .cmd{margin-left:6px}
.tty-head .cmd b{color:var(--green)}
.tty-body{padding:18px}
h1{
  font-size:24px; font-weight:800; letter-spacing:3px; color:var(--txmax); margin:0 0 2px;
}
.sub{font-size:11px; color:var(--mut); letter-spacing:2px}
.hrow{display:flex; gap:14px; align-items:center}
.avatar{width:48px; height:48px; border-radius:50%; flex:0 0 auto; border:1px solid var(--bdhi)}
.ustats{font-size:12px; color:var(--mut); margin:5px 0 2px; font-variant-numeric:tabular-nums}
.ustats b{color:var(--txhi)}
.stats{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:18px}
.stat{background:var(--s1); border:1px solid var(--bd); border-left:3px solid var(--green); border-radius:6px; padding:12px 14px}
.stat .n{font-size:30px; font-weight:800; color:var(--txmax); line-height:1}
.stat.cl{border-left-color:var(--amber)}
.stat .l{font-size:9px; letter-spacing:2px; color:var(--mut); margin-top:6px; text-transform:uppercase}
.section-title{font-size:11px; letter-spacing:2px; color:var(--mut); text-transform:uppercase; margin:26px 0 10px}
svg{display:block; width:100%; height:auto}
table{width:100%; border-collapse:collapse; font-size:12px}
td{padding:7px 8px; border-bottom:1px solid var(--bd)}
.barcell{position:relative; min-width:90px}
.cnt{color:var(--txhi); font-weight:700}
input[type=checkbox]{accent-color:var(--green); width:14px; height:14px; margin:0; vertical-align:middle}
@media(max-width:760px){.stats{grid-template-columns:repeat(2,1fr)}}
.refbar{height:5px; border-radius:3px; background:var(--cyan)}
.pill{display:inline-block; font-size:9px; letter-spacing:1px; padding:1px 6px; border:1px solid var(--bd); border-radius:10px; color:var(--mut)}
.foot{font-size:10px; color:var(--mut); margin-top:30px; line-height:1.7}
.skip{font-size:11px; color:var(--red)}
.lightbanner{font-size:11px; color:var(--amber); border:1px solid var(--bd); border-left:3px solid var(--amber); border-radius:4px; padding:7px 12px; margin:0 0 16px; letter-spacing:.3px}
.lightbanner b{color:var(--txhi); letter-spacing:1px; text-transform:uppercase}
#chart{cursor:crosshair}
[hidden]{display:none !important}
.tip{position:fixed; z-index:10000; pointer-events:none; display:none; background:var(--s0);
  border:1px solid var(--green); border-radius:5px; padding:7px 10px; font-size:11px;
  color:var(--txhi); box-shadow:0 4px 12px rgba(0,0,0,.35); white-space:nowrap; letter-spacing:.3px}
.tip b{color:var(--txmax)}
.controls{display:flex; gap:14px; align-items:center; margin:26px 0 10px; font-size:11px; color:var(--mut)}
.controls label{display:inline-flex; align-items:center; gap:5px; cursor:pointer; user-select:none; letter-spacing:1px}
.controls .section-title{margin:0}
.pr-head{display:flex; justify-content:space-between; align-items:center; margin-bottom:8px}
.toggle{display:inline-flex; gap:5px; flex-wrap:wrap}
.toggle a{cursor:pointer; color:var(--mut); padding:2px 10px; border:1px solid var(--bd); border-radius:4px; font-size:10px; letter-spacing:1px; user-select:none}
.toggle a:hover{color:var(--txhi)}
.toggle a.on{color:var(--green); border-color:var(--green)}
.repodd{position:relative; font-size:10px}
.repodd summary{cursor:pointer; list-style:none; padding:2px 10px; border:1px solid var(--bd); border-radius:4px; color:var(--mut); letter-spacing:1px; user-select:none}
.repodd summary::-webkit-details-marker{display:none}
.repodd[open] summary{color:var(--green); border-color:var(--green)}
.repodd-menu{position:fixed; top:-9999px; left:-9999px; z-index:9000; background:var(--s0); border:1px solid var(--bdhi); border-radius:6px; padding:6px; min-width:210px; max-height:340px; overflow:auto; box-shadow:0 8px 24px rgba(0,0,0,.45); scrollbar-width:thin; scrollbar-color:var(--s2) var(--s0)}
*::-webkit-scrollbar{width:10px; height:10px}
*::-webkit-scrollbar-track{background:var(--s0)}
*::-webkit-scrollbar-thumb{background:var(--s2); border-radius:6px; border:2px solid var(--s0)}
*::-webkit-scrollbar-thumb:hover{background:var(--bdhi)}
html{scrollbar-width:thin; scrollbar-color:var(--s2) var(--bg)}
.repodd-actions{display:flex; gap:4px; margin-bottom:6px}
.repodd-actions a{cursor:pointer; padding:2px 8px; border:1px solid var(--bd); border-radius:4px; color:var(--mut)}
.repodd-actions a:hover{color:var(--green); border-color:var(--green)}
.rdd-item{display:flex; align-items:center; gap:8px; padding:3px 6px; cursor:pointer; border-radius:4px; white-space:nowrap}
.rdd-item:hover{background:var(--s1)}
.rdd-item span{flex:1; overflow:hidden; text-overflow:ellipsis}
.rdd-item b{color:var(--txhi); font-variant-numeric:tabular-nums}
.legend2{display:flex; align-items:center; flex-wrap:wrap; gap:8px 16px; margin-top:10px; font-size:10px; color:var(--tx)}
.legend2 .sw{display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:middle}
.legend2 b{color:var(--txhi)}
.trend{font-weight:700; font-size:11px; font-variant-numeric:tabular-nums; margin-left:4px}
.trend.up{color:var(--green)} .trend.down{color:var(--red)} .trend.flat{color:var(--mut)}
.tpair{color:var(--mut)}
.tl{color:var(--txhi); font-weight:700}
.tsep{margin:0 5px; color:var(--mut)}
.insight{margin-top:12px; font-size:11px; color:var(--mut); letter-spacing:.3px; line-height:1.7}
.insight b{color:var(--txhi)}
.iseg{white-space:nowrap}
.legend2>span{white-space:nowrap}
.grefs table{width:100%}
.grefs td{padding:6px 8px; border-bottom:1px solid var(--bd)}
.grefs .muted{color:var(--mut)}
.repo-grid{display:grid; grid-template-columns:repeat(auto-fill, minmax(min(280px,100%),1fr)); grid-auto-rows:1fr; gap:16px; margin-bottom:8px}
.repo-card{position:relative; min-width:0; display:flex; flex-direction:column; background:var(--s0); border:1px solid var(--bd); border-radius:8px; padding:14px; transition:border-color .12s, opacity .12s}
.repo-card:hover{border-color:var(--green)}
.repo-card.off{opacity:.4}
.repo-card .sel{position:absolute; top:11px; right:11px; z-index:2; accent-color:var(--green); width:15px; height:15px; cursor:pointer; margin:0}
.chead{display:flex; gap:12px; align-items:center; margin-bottom:14px; padding-right:24px}
.cthumb{width:92px; height:52px; flex:0 0 auto; object-fit:cover; object-position:top; border-radius:4px; background:var(--bg)}
.cthumb-np{width:92px; height:52px; flex:0 0 auto; border-radius:4px; display:flex; align-items:center; justify-content:center; background:var(--bg); font-weight:700; font-size:1.4rem; letter-spacing:-1px;
  background-image:repeating-linear-gradient(0deg, rgba(146,131,116,.06) 0, rgba(146,131,116,.06) 1px, transparent 1px, transparent 4px)}
.chead-t{min-width:0}
.chead-t .rtitle{font-size:14px; font-weight:600; color:var(--green); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.chead-t .cstars{font-size:13px; color:var(--amber); margin-top:5px; font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.pills .pill{margin-left:6px}
.cbig{display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:14px}
.cbig .cl{font-size:9px; letter-spacing:1.5px; text-transform:uppercase; color:var(--mut)}
.cbig .cnum{font-size:23px; font-weight:800; color:var(--txhi); font-variant-numeric:tabular-nums; line-height:1.15; margin-top:2px}
.crefs{display:flex; flex-direction:column; gap:7px; margin-bottom:12px}
.rb{display:grid; grid-template-columns:1fr 84px auto; gap:9px; align-items:center; font-size:11px}
.rbn{color:var(--tx); overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.rbt{height:4px; border-radius:2px; background:var(--s2); overflow:hidden}
.rbf{display:block; height:100%; background:var(--green)}
.rbc{color:var(--txhi); font-variant-numeric:tabular-nums; font-weight:700}
.crefs .none{color:var(--mut); font-size:11px}
.csec{font-size:12px; color:var(--mut); border-top:1px solid var(--bd); padding-top:10px; margin-top:auto; font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.csec b{color:var(--txhi)}
.csec .sep{opacity:.45; margin:0 3px}
.rlink,.csl{color:inherit; text-decoration:none}
.rlink:hover,.csl:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="wrap">
  <div class="themebar">
    <span>theme</span>
    <span class="toggle" id="theme-toggle"><a data-t="gruvbox" class="on">gruvbox</a><a data-t="rose-pine">rose pine</a><a data-t="everforest">everforest</a><a data-t="gruvbox-light">gruvbox light</a><a data-t="catppuccin-latte">catppuccin latte</a><a data-t="tokyo-night-light">tokyo night light</a></span>
  </div>
  <div id="lightbanner"></div>
  <div class="tty">
    <div class="tty-head">
      <span class="swrow"></span>
      <span class="cmd">$ <b>gh-traffic</b> --user <span id="who"></span></span>
    </div>
    <div class="tty-body">
      <div class="hrow">
        <img id="avatar" class="avatar" alt="" hidden>
        <div>
          <h1>GH&nbsp;TRAFFIC</h1>
          <div class="ustats" id="ustats"></div>
          <div class="sub" id="meta"></div>
        </div>
      </div>
      <div class="stats">
        <div class="stat"><div class="n" id="t-views">0</div><div class="l">Views</div></div>
        <div class="stat"><div class="n" id="t-vu">0</div><div class="l">Unique visitors</div></div>
        <div class="stat cl"><div class="n" id="t-clones">0</div><div class="l">Clones</div></div>
        <div class="stat cl"><div class="n" id="t-cu">0</div><div class="l">Unique cloners</div></div>
      </div>
      <div class="insight" id="insight"></div>
      <div class="pr-head">
        <span class="toggle"><a id="cm-total" class="on">Total</a><a id="cm-perrepo">Per repo</a></span>
        <span class="toggle" id="metric-toggle" style="display:none"><a id="pr-views" class="on">views</a><a id="pr-clones">clones</a></span>
        <details class="repodd" id="repo-dd" style="display:none">
          <summary>repos <span id="repo-dd-count" class="muted"></span></summary>
          <div class="repodd-menu">
            <div class="repodd-actions"><a id="rdd-all">all</a><a id="rdd-none">none</a><a id="rdd-top">top 10</a></div>
            <div id="repo-dd-list"></div>
          </div>
        </details>
      </div>
      <svg id="chart" viewBox="0 0 960 220" preserveAspectRatio="none"></svg>
      <div class="legend2" id="chart-legend"></div>
    </div>
  </div>

  <div class="controls">
    <span class="section-title" style="margin:0">Repositories</span>
    <label><input type="checkbox" id="nofork"> exclude forks</label>
    <span class="muted">· sort</span>
    <span class="toggle" id="sort-toggle"><a data-s="views" class="on">views</a><a data-s="clones">clones</a><a data-s="stars">stars</a><a data-s="updated">updated</a><a data-s="name">name</a></span>
  </div>
  <div id="grid" class="repo-grid"></div>
  <div id="skip"></div>

  <div class="tty" style="margin-top:26px">
    <div class="tty-head">
      <span class="swrow"></span>
      <span class="cmd">$ <b>gh-traffic</b> --referrers</span>
    </div>
    <div class="tty-body">
      <div class="section-title" style="margin:0 0 8px">Top referring sites — all selected repos (14-day)</div>
      <div class="grefs" id="grefs"></div>
    </div>
  </div>

  <div class="foot" id="foot"></div>
</div>
<div id="tip" class="tip"></div>

<script>
const DATA = /*__DATA__*/null;
const $ = s => document.querySelector(s);
const fmt = n => (n||0).toLocaleString('en-US');
const THEMES={
  gruvbox:{bg:'#0c0d0f',s0:'#131415',s1:'#3c3836',s2:'#504945',bd:'#3c3836',bdhi:'#504945',tx:'#ebdbb2',txhi:'#fbf1c7',txmax:'#fbf1c7',mut:'#928374',green:'#b8bb26',amber:'#fabd2f',cyan:'#83a598',red:'#fb4934',orange:'#fe8019',grid:'#504945',axisLabel:'#a89984',axisWeekend:'#7c6f64',baseline:'#3c3836',marker:'#665c54',palette:['#b8bb26','#83a598','#fabd2f','#d3869b','#fe8019','#8ec07c','#fb4934','#458588','#d65d0e','#b16286','#689d6a','#d79921']},
  'rose-pine':{bg:'#191724',s0:'#1f1d2e',s1:'#26233a',s2:'#403d52',bd:'#26233a',bdhi:'#403d52',tx:'#e0def4',txhi:'#e0def4',txmax:'#e0def4',mut:'#908caa',green:'#9ccfd8',amber:'#f6c177',cyan:'#31748f',red:'#eb6f92',orange:'#ebbcba',grid:'#403d52',axisLabel:'#908caa',axisWeekend:'#6e6a86',baseline:'#26233a',marker:'#524f67',palette:['#9ccfd8','#c4a7e7','#f6c177','#eb6f92','#31748f','#ebbcba','#9ccfd8','#c4a7e7','#f6c177','#eb6f92','#31748f','#ebbcba']},
  everforest:{bg:'#1e2326',s0:'#272e33',s1:'#2e383c',s2:'#374145',bd:'#2e383c',bdhi:'#414b50',tx:'#d3c6aa',txhi:'#d3c6aa',txmax:'#d3c6aa',mut:'#859289',green:'#a7c080',amber:'#dbbc7f',cyan:'#7fbbb3',red:'#e67e80',orange:'#e69875',grid:'#374145',axisLabel:'#9da9a0',axisWeekend:'#859289',baseline:'#2e383c',marker:'#414b50',palette:['#a7c080','#7fbbb3','#dbbc7f','#d699b6','#e69875','#83c092','#e67e80','#7fbbb3','#dbbc7f','#d699b6','#e69875','#83c092']},
  'gruvbox-light':{bg:'#f9f5d7',s0:'#ebdbb2',s1:'#d5c4a1',s2:'#bdae93',bd:'#d5c4a1',bdhi:'#bdae93',tx:'#504945',txhi:'#3c3836',txmax:'#282828',mut:'#665c54',green:'#79740e',amber:'#b57614',cyan:'#427b58',red:'#9d0006',orange:'#af3a03',grid:'#d5c4a1',axisLabel:'#665c54',axisWeekend:'#bdae93',baseline:'#d5c4a1',marker:'#bdae93',palette:['#79740e','#076678','#b57614','#8f3f71','#af3a03','#427b58','#9d0006','#d65d0e','#79740e','#076678','#b57614','#8f3f71']},
  'catppuccin-latte':{bg:'#eff1f5',s0:'#e6e9ef',s1:'#ccd0da',s2:'#bcc0cc',bd:'#ccd0da',bdhi:'#bcc0cc',tx:'#4c4f69',txhi:'#4c4f69',txmax:'#4c4f69',mut:'#7c7f93',green:'#40a02b',amber:'#df8e1d',cyan:'#179299',red:'#d20f39',orange:'#fe640b',grid:'#ccd0da',axisLabel:'#6c6f85',axisWeekend:'#acb0be',baseline:'#ccd0da',marker:'#bcc0cc',palette:['#40a02b','#1e66f5','#df8e1d','#8839ef','#fe640b','#179299','#d20f39','#dd7878','#40a02b','#1e66f5','#df8e1d','#8839ef']},
  'tokyo-night-light':{bg:'#d5d6db',s0:'#e9e9ed',s1:'#dfe0e5',s2:'#cbccd1',bd:'#cbccd1',bdhi:'#9699a3',tx:'#343b59',txhi:'#1a1b26',txmax:'#1a1b26',mut:'#4c505e',green:'#485e30',amber:'#965027',cyan:'#166775',red:'#8c4351',orange:'#965027',grid:'#cbccd1',axisLabel:'#4c505e',axisWeekend:'#9699a3',baseline:'#cbccd1',marker:'#9699a3',palette:['#485e30','#34548a','#965027','#5a4a78','#8c4351','#3e6968','#166775','#485e30','#34548a','#965027','#5a4a78','#8c4351']}
};
const VARKEYS=['bg','s0','s1','s2','bd','bdhi','tx','txhi','txmax','mut','green','amber','cyan','red'];
let T=THEMES.gruvbox, GREEN=T.green, AMBER=T.amber, PALETTE=T.palette;
function applyTheme(name){
  T=THEMES[name]||THEMES.gruvbox; GREEN=T.green; AMBER=T.amber; PALETTE=T.palette;
  const rs=document.documentElement.style; VARKEYS.forEach(k=>rs.setProperty('--'+k,T[k]));
  document.querySelectorAll('#theme-toggle a').forEach(a=>a.className=a.dataset.t===name?'on':'');
  document.querySelectorAll('.swrow').forEach(sw=>sw.innerHTML=T.palette.map(c=>`<span class="sw2" style="background:${c}"></span>`).join(''));
  renderCards(); renderTotals();
}
let sortKey='views', sortDir=-1;
const selected = new Set(DATA.repos.map(r=>r.name));

function dailyMap(repo, kind){
  // prefer merged history (may exceed 14d), else the live 14d daily series
  const src = (repo[kind].history && repo[kind].history.length) ? repo[kind].history : repo[kind].daily;
  const m = new Map();
  src.forEach(d => m.set(d.date, (m.get(d.date)||0) + d.count));
  return m;
}
// GitHub omits zero-traffic days, so a chart would skip them. Build a CONTINUOUS
// daily axis (gaps = 0) spanning at least `minDays` up to the latest date present.
function dateRange(dataDates, minDays){
  if(!dataDates.length) return [];
  const s=[...dataDates].sort();
  const ymd=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  const max=new Date(s[s.length-1]+'T12:00:00');
  let start=new Date(s[0]+'T12:00:00');
  const ws=new Date(max); ws.setDate(ws.getDate()-(minDays-1));
  if(ws<start) start=ws;
  const out=[], d=new Date(start);
  while(d<=max){ out.push(ymd(d)); d.setDate(d.getDate()+1); }
  return out;
}
function allDates(kind){
  const s = new Set();
  DATA.repos.forEach(r => { if(selected.has(r.name)) dailyMap(r,kind).forEach((_,d)=>s.add(d)); });
  return [...s].sort();
}
function seriesFor(kind){
  const dates = allDates(kind);
  const totals = dates.map(d => {
    let t=0; DATA.repos.forEach(r=>{ if(selected.has(r.name)){ const v=dailyMap(r,kind).get(d); if(v) t+=v; } });
    return t;
  });
  return {dates, totals};
}

// ── inline SVG line chart (no libs) ──
function lineChart(svg, datasets, W=960, H=220, labels=null){
  const hasLabels = !!(labels && labels.length);
  const pad={l: hasLabels?20:6, r: hasLabels?20:6, t:14, b: hasLabels?38:18};
  let maxY=1, n=0;
  datasets.forEach(ds=>{ ds.vals.forEach(v=>maxY=Math.max(maxY,v)); n=Math.max(n,ds.vals.length); });
  const x = i => pad.l + (n<=1?0:(i/(n-1))*(W-pad.l-pad.r));
  const y = v => H-pad.b - (v/maxY)*(H-pad.t-pad.b);
  const yb = (H-pad.b).toFixed(1);
  let out='';
  // week structure + date/weekday axis (drawn behind the data lines)
  if(hasLabels){
    const WD=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    const step=Math.max(1,Math.ceil(n/24));  // label every day up to ~24; thin only beyond
    for(let i=0;i<labels.length && i<n;i++){
      const dt=new Date(labels[i]+'T12:00:00'), dow=dt.getDay(), weekend=(dow===0||dow===6);
      if(dow===1){ // Monday = week start
        out+=`<line x1="${x(i).toFixed(1)}" y1="${pad.t}" x2="${x(i).toFixed(1)}" y2="${yb}" stroke="${T.grid}" stroke-dasharray="2 3"/>`;
      }
      if(i%step===0 || dow===1 || i===n-1){
        const col=weekend?T.axisWeekend:T.axisLabel;
        const dd=labels[i].slice(8,10)+'.'+labels[i].slice(5,7);  // DD.MM
        out+=`<text x="${x(i).toFixed(1)}" y="${H-pad.b+14}" fill="${col}" font-size="9" text-anchor="middle">${WD[dow]}</text>`;
        out+=`<text x="${x(i).toFixed(1)}" y="${H-pad.b+25}" fill="${col}" font-size="9" text-anchor="middle">${dd}</text>`;
      }
    }
  }
  // baseline
  out+=`<line x1="${pad.l}" y1="${yb}" x2="${W-pad.r}" y2="${yb}" stroke="${T.baseline}"/>`;
  datasets.forEach(ds=>{
    if(!ds.vals.length) return;
    const pts = ds.vals.map((v,i)=>`${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    // area
    out+=`<polygon points="${x(0).toFixed(1)},${yb} ${pts} ${x(ds.vals.length-1).toFixed(1)},${yb}" fill="${ds.color}" opacity="0.08"/>`;
    out+=`<polyline points="${pts}" fill="none" stroke="${ds.color}" stroke-width="2"/>`;
  });
  out+=`<text x="${pad.l}" y="11" fill="${T.mut}" font-size="9">peak ${fmt(maxY)}</text>`;
  if(hasLabels){ // hidden hover marker (line + one dot per series), positioned on mousemove
    out+=`<g class="hov" style="display:none"><line stroke="${T.marker}" y1="${pad.t}" y2="${yb}"/>`+
         datasets.map(ds=>`<circle r="3.2" fill="${ds.color}"/>`).join('')+`</g>`;
  }
  svg.__geom={W,H,padL:pad.l,padR:pad.r,padT:pad.t,padB:pad.b,n,maxY};
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.innerHTML=out;
}

const WDAY=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
// hover read-out: nearest day under the cursor → date + each series value.
// Marker elements are created by lineChart (SVG markup), queried here — no createElementNS.
function attachHover(svg, tip, labels, series){
  const g=svg.__geom; if(!g) return;
  const marker=svg.querySelector('.hov'); if(!marker) return;
  const vline=marker.querySelector('line');
  const dots=[...marker.querySelectorAll('circle')];
  const X=i=> g.padL+(g.n<=1?0:(i/(g.n-1))*(g.W-g.padL-g.padR));
  const Y=v=> g.H-g.padB-(v/g.maxY)*(g.H-g.padT-g.padB);
  svg.onmousemove=e=>{
    const r=svg.getBoundingClientRect(); if(!r.width||!g.n) return;
    const vbx=(e.clientX-r.left)/r.width*g.W;
    let idx=g.n<=1?0:Math.round((vbx-g.padL)/((g.W-g.padL-g.padR)/(g.n-1)));
    idx=Math.max(0,Math.min(g.n-1,idx));
    const xx=X(idx).toFixed(1);
    vline.setAttribute('x1',xx); vline.setAttribute('x2',xx);
    dots.forEach((c,k)=>{ c.setAttribute('cx',xx); c.setAttribute('cy',Y(series[k].vals[idx]||0).toFixed(1)); });
    marker.style.display='';
    const d=labels[idx], dd=d.slice(8,10)+'.'+d.slice(5,7)+'.'+d.slice(0,4);
    let html=`<b>${WDAY[new Date(d+'T12:00:00').getDay()]} ${dd}</b>`;
    series.slice().sort((a,b)=>(b.vals[idx]||0)-(a.vals[idx]||0)).forEach(s=>{ html+=`<br><span style="color:${s.color}">■</span> ${s.name} <b>${fmt(s.vals[idx]||0)}</b>`; });
    tip.innerHTML=html; tip.style.display='block';
    const tw=tip.offsetWidth, th=tip.offsetHeight;
    let px=e.clientX-tw-14; if(px<6) px=6;                       // always to the LEFT of the cursor
    let py=e.clientY+14; if(py+th>window.innerHeight) py=window.innerHeight-th-6; if(py<6) py=6;  // clamp, no up-flip
    tip.style.left=px+'px'; tip.style.top=py+'px';
  };
  svg.onmouseleave=()=>{ tip.style.display='none'; marker.style.display='none'; };
}

function renderTotals(){
  let views=0,vu=0,clones=0,cu=0;
  DATA.repos.forEach(r=>{ if(selected.has(r.name)){
    views+=r.views.count; vu+=r.views.uniques; clones+=r.clones.count; cu+=r.clones.uniques;
  }});
  $('#t-views').textContent=fmt(views); $('#t-vu').textContent=fmt(vu);
  $('#t-clones').textContent=fmt(clones); $('#t-cu').textContent=fmt(cu);
  renderChart();
  renderGlobalReferrers();
  renderInsight();
}

// ── per-repo chart: one line per selected repo, capped via the top-N toggle ──
let perRepoMetric='views';
function repoTotal(r, metric){ let t=0; dailyMap(r,metric).forEach(v=>t+=v); return t; }
let chartMode='total';
const chartSel=new Set();   // repos drawn in the per-repo chart (driven by the dropdown)
// trend = recent half of the window vs the prior half (honest, no extrapolation)
function trend(vals){
  const n=vals.length; if(n<4) return null;
  const h=Math.floor(n/2);
  const prev=vals.slice(0,h).reduce((a,b)=>a+b,0), recent=vals.slice(h).reduce((a,b)=>a+b,0);
  if(prev===0 && recent===0) return null;
  const pct = prev===0 ? null : Math.round((recent-prev)/prev*100);   // null = from-zero (no baseline) → rendered as "NA"
  return {pct, dir: recent>prev?'up':recent<prev?'down':'flat', half:n-h};
}
function trendBadge(t){
  // NA = no computable trend (too little data, or grew from a zero baseline)
  if(!t) return `<span class="trend flat" title="not enough data for a trend">NA</span>`;
  if(t.pct===null) return `<span class="trend flat" title="grew from a zero baseline — no % possible">NA</span>`;
  const arrow = t.dir==='up'?'&#9650;':t.dir==='down'?'&#9660;':'&#8211;';
  return `<span class="trend ${t.dir}" title="recent half of the window vs the prior half">${arrow} ${t.pct>0?'+':''}${t.pct}%</span>`;
}
// labelled per-metric trend ("v ▲200%" / "c NA") for the per-repo legend
function metricTrend(label, vals){
  return `<span class="tl">${label}</span>${trendBadge(trend(vals))}`;
}
function renderChart(){
  const svg=$('#chart'), legend=$('#chart-legend');
  if(chartMode==='total'){
    $('#metric-toggle').style.display='none'; $('#repo-dd').style.display='none';
    const v=seriesFor('views'), c=seriesFor('clones');
    const dates=dateRange([...new Set([...v.dates,...c.dates])], 14);
    const vm=new Map(v.dates.map((d,i)=>[d,v.totals[i]])), cm=new Map(c.dates.map((d,i)=>[d,c.totals[i]]));
    const vv=dates.map(d=>vm.get(d)||0), cc=dates.map(d=>cm.get(d)||0);
    lineChart(svg, [{color:GREEN,vals:vv},{color:AMBER,vals:cc}], 960, 220, dates);
    attachHover(svg, $('#tip'), dates, [{name:'views',color:GREEN,vals:vv},{name:'clones',color:AMBER,vals:cc}]);
    const tv=trend(vv), tc=trend(cc);
    legend.innerHTML=`<span><span class="sw" style="background:${GREEN}"></span>views${trendBadge(tv)}</span><span><span class="sw" style="background:${AMBER}"></span>clones${trendBadge(tc)}</span><span class="muted">— selected repos · last ${(tv||tc||{}).half||7}d vs prior</span>`;
    $('#cm-total').className='on'; $('#cm-perrepo').className='';
  } else {
    $('#metric-toggle').style.display=''; $('#repo-dd').style.display='';
    const metric=perRepoMetric;
    const shown=DATA.repos.filter(r=>chartSel.has(r.name)).sort((a,b)=>repoTotal(b,metric)-repoTotal(a,metric));
    const ds=new Set(); shown.forEach(r=>dailyMap(r,metric).forEach((_,d)=>ds.add(d)));
    const dates=dateRange([...ds], 14);
    const series=shown.map((r,i)=>({name:r.name, color:PALETTE[i%PALETTE.length], vals:dates.map(d=>dailyMap(r,metric).get(d)||0)}));
    lineChart(svg, series.map(s=>({color:s.color,vals:s.vals})), 960, 220, dates);
    attachHover(svg, $('#tip'), dates, series);
    legend.innerHTML = shown.length
      ? shown.map((r,i)=>{
          const vv=dates.map(d=>dailyMap(r,'views').get(d)||0), cv=dates.map(d=>dailyMap(r,'clones').get(d)||0);
          return `<span><span class="sw" style="background:${PALETTE[i%PALETTE.length]}"></span>${esc(r.name)} <b>${fmt(repoTotal(r,metric))}</b> <span class="tpair">(${metricTrend('v',vv)}<span class="tsep">/</span>${metricTrend('c',cv)})</span></span>`;
        }).join('')
      : `<span class="muted">no repos picked — choose some in the “repos” menu →</span>`;
    $('#cm-total').className=''; $('#cm-perrepo').className='on';
    $('#pr-views').className = metric==='views'?'on':''; $('#pr-clones').className = metric==='clones'?'on':'';
    renderRepoDropdown();
  }
}
// per-repo chart selector: all / none / top 10 + an individual checkbox per repo
function renderRepoDropdown(){
  const list=$('#repo-dd-list');
  const repos=[...DATA.repos].sort((a,b)=>repoTotal(b,perRepoMetric)-repoTotal(a,perRepoMetric));
  list.innerHTML=repos.map(r=>`<label class="rdd-item"><input type="checkbox" data-r="${esc(r.name)}"${chartSel.has(r.name)?' checked':''}><span>${esc(r.name)}</span><b>${fmt(repoTotal(r,perRepoMetric))}</b></label>`).join('');
  list.querySelectorAll('input').forEach(cb=>cb.addEventListener('change',()=>{
    cb.checked?chartSel.add(cb.dataset.r):chartSel.delete(cb.dataset.r); renderChart();
  }));
  $('#repo-dd-count').textContent=`(${chartSel.size}/${DATA.repos.length})`;
}
function setChartSel(names){ chartSel.clear(); names.forEach(n=>chartSel.add(n)); renderChart(); }
function topRepos(n){ return [...DATA.repos].sort((a,b)=>repoTotal(b,perRepoMetric)-repoTotal(a,perRepoMetric)).slice(0,n).map(r=>r.name); }

// referrers summed across the selected repos (uniques summed too — overcounts cross-repo)
function aggregatedReferrers(){
  const m=new Map();
  DATA.repos.forEach(r=>{ if(selected.has(r.name)) r.referrers.forEach(x=>{
    const e=m.get(x.referrer)||{referrer:x.referrer,count:0,uniques:0};
    e.count+=x.count; e.uniques+=x.uniques; m.set(x.referrer,e);
  }); });
  return [...m.values()].sort((a,b)=>b.count-a.count);
}
function renderGlobalReferrers(){
  const agg=aggregatedReferrers().slice(0,10), el=$('#grefs');
  if(!agg.length){ el.innerHTML='<span class="muted">no referrer data for the selected repos</span>'; return; }
  const max=agg[0].count;
  el.innerHTML='<table><tbody>'+agg.map(x=>{
    const w=Math.round(x.count/Math.max(1,max)*240);
    return `<tr><td>${esc(x.referrer)}</td><td class="barcell"><div class="refbar" style="width:${w}px"></div></td><td class="cnt">${fmt(x.count)}</td><td class="muted">${fmt(x.uniques)}u</td></tr>`;
  }).join('')+'</tbody></table>';
}
function renderInsight(){
  const sel=DATA.repos.filter(r=>selected.has(r.name));
  if(!sel.length){ $('#insight').innerHTML=''; return; }
  const tv=sel.reduce((a,b)=>b.views.count>a.views.count?b:a);
  const tc=sel.reduce((a,b)=>b.clones.count>a.clones.count?b:a);
  const ts=aggregatedReferrers()[0];
  let oi=0, op=0; sel.forEach(r=>{ oi+=Math.max(0,r.open_issues_total-(r.open_prs||0)); op+=(r.open_prs||0); });
  const segs=[
    `★ top views <b>${esc(tv.name)}</b> (${fmt(tv.views.count)})`,
    `⎘ top clones <b>${esc(tc.name)}</b> (${fmt(tc.clones.count)})`,
  ];
  if(ts) segs.push(`↗ top source <b>${esc(ts.referrer)}</b> (${fmt(ts.count)})`);
  const gl=(base,q,txt)=>`<a class="csl" href="https://github.com/${base}?q=${encodeURIComponent(q)}" target="_blank" rel="noopener noreferrer">${txt}</a>`;
  const U=DATA.user;
  segs.push(`◍ in your repos: ${gl('issues',`is:open is:issue user:${U}`,`<b>${fmt(oi)}</b> issues`)} / ${gl('pulls',`is:open is:pr user:${U}`,`<b>${fmt(op)}</b> PRs`)}`);
  const ai=DATA.authored_issues, ap=DATA.authored_prs;
  if(ai!=null || ap!=null)
    segs.push(`✎ you opened: ${gl('issues',`is:open is:issue author:${U}`,`<b>${ai==null?'?':fmt(ai)}</b> issues`)} / ${gl('pulls',`is:open is:pr author:${U}`,`<b>${ap==null?'?':fmt(ap)}</b> PRs`)}`);
  else
    segs.push(`<span class="muted">✎ you opened: search n/a (token lacks search)</span>`);
  // each segment is nowrap → the line only breaks between segments (at the · separators)
  $('#insight').innerHTML=segs.map(s=>`<span class="iseg">${s}</span>`).join(' · ');
}

const PILL=r=>`${r.private?'<span class="pill">private</span>':''}${r.fork?'<span class="pill">fork</span>':''}`;
function monoTint(name){ let h=0; for(let i=0;i<name.length;i++) h+=name.charCodeAt(i);
  return T.palette[h%T.palette.length]+'99'; }
function initials(r){ const b=r.name.replace(/^omarchy-/,'').replace(/-theme$/,''); return ((b||r.name).slice(0,2)).toUpperCase(); }
// top referrers as horizontal bars (vyrx "Online" language-bar style)
function refBars(r){
  const refs=r.referrers.slice(0,3);
  if(!refs.length) return `<div class="none">no referrers (14d)</div>`;
  const max=refs[0].count;
  return refs.map((x,i)=>{
    const w=Math.round(x.count/Math.max(1,max)*100);
    return `<div class="rb"><span class="rbn">${esc(x.referrer)}</span><span class="rbt"><span class="rbf" style="width:${w}%; background:${PALETTE[i%PALETTE.length]}"></span></span><span class="rbc">${fmt(x.count)}</span></div>`;
  }).join('');
}
// "updated 3d ago" from pushed_at (the report runs in a browser, Date.now() is fine)
function relTime(iso){
  if(!iso) return '';
  const d=Math.floor((Date.now()-new Date(iso).getTime())/86400000);
  if(d<=0) return 'today';
  if(d===1) return 'yesterday';
  if(d<30) return d+'d ago';
  if(d<365) return Math.floor(d/30)+'mo ago';
  return Math.floor(d/365)+'y ago';
}
function renderCards(){
  const val=(r,k)=> k==='name'?r.name.toLowerCase() : k==='stars'?r.stars : k==='updated'?(Date.parse(r.pushed_at)||0) : r[k].count;
  const rows=[...DATA.repos].sort((a,b)=>{ const A=val(a,sortKey),B=val(b,sortKey);
    if(sortKey==='name') return A<B?-1:A>B?1:0; return B-A; });
  const grid=$('#grid'); grid.innerHTML='';
  rows.forEach(r=>{
    const iss=Math.max(0,r.open_issues_total-(r.open_prs||0)), prs=r.open_prs==null?'?':fmt(r.open_prs);
    const card=document.createElement('div');
    card.className='repo-card'+(selected.has(r.name)?'':' off');
    card.innerHTML=`
      <input class="sel" type="checkbox" title="include in totals" ${selected.has(r.name)?'checked':''}>
      <div class="chead">
        ${r.thumb?`<img class="cthumb" loading="lazy" decoding="async" alt="" src="${r.thumb}">`
                 :`<div class="cthumb-np" style="color:${monoTint(r.name)}">${esc(initials(r))}</div>`}
        <div class="chead-t">
          <div class="rtitle"><a class="rlink" href="https://github.com/${esc(DATA.user)}/${esc(r.name)}" target="_blank" rel="noopener noreferrer">${esc(r.name)}</a><span class="pills">${PILL(r)}</span></div>
          <div class="cstars">&#9733; ${fmt(r.stars)} stars${r.watchers!=null?` &nbsp;·&nbsp; ${fmt(r.watchers)} watching`:''}</div>
        </div>
      </div>
      <div class="cbig">
        <div><div class="cl">views (14d)</div><div class="cnum">${fmt(r.views.count)}</div></div>
        <div><div class="cl">clones</div><div class="cnum">${fmt(r.clones.count)}</div></div>
      </div>
      <div class="crefs">${refBars(r)}</div>
      <div class="csec"><span style="color:${T.orange}">&#9711;</span> <a class="csl" href="https://github.com/${esc(DATA.user)}/${esc(r.name)}/issues" target="_blank" rel="noopener noreferrer"><b>${fmt(iss)}</b> issues</a> <span class="sep">·</span> <span style="color:${T.cyan}">&#8644;</span> <a class="csl" href="https://github.com/${esc(DATA.user)}/${esc(r.name)}/pulls" target="_blank" rel="noopener noreferrer"><b>${prs}</b> PRs</a>${r.pushed_at?` <span class="sep">·</span> updated <b>${relTime(r.pushed_at)}</b>`:''}</div>`;
    card.querySelector('input').addEventListener('click',e=>{
      e.target.checked?selected.add(r.name):selected.delete(r.name);
      card.classList.toggle('off', !e.target.checked);
      renderTotals();
    });
    grid.appendChild(card);
  });
}
const esc = s => String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// card sort
document.querySelectorAll('#sort-toggle a').forEach(a=>a.addEventListener('click',()=>{
  sortKey=a.dataset.s;
  document.querySelectorAll('#sort-toggle a').forEach(x=>x.className = x.dataset.s===sortKey?'on':'');
  renderCards();
}));

// bulk include/exclude all forked repos from the totals
$('#nofork').addEventListener('change',e=>{
  DATA.repos.forEach(r=>{ if(r.fork){ e.target.checked ? selected.delete(r.name) : selected.add(r.name); } });
  renderCards(); renderTotals();
});

// chart mode (Total ⇄ Per repo) + per-repo metric toggle
$('#cm-total').addEventListener('click',()=>{ chartMode='total'; renderChart(); });
$('#cm-perrepo').addEventListener('click',()=>{ chartMode='perrepo'; renderChart(); });
$('#pr-views').addEventListener('click',()=>{ perRepoMetric='views'; renderChart(); });
$('#pr-clones').addEventListener('click',()=>{ perRepoMetric='clones'; renderChart(); });
$('#rdd-all').addEventListener('click',()=>setChartSel(DATA.repos.map(r=>r.name)));
$('#rdd-none').addEventListener('click',()=>setChartSel([]));
$('#rdd-top').addEventListener('click',()=>setChartSel(topRepos(10)));
// the menu is position:fixed (the chart card clips overflow) — place it under the summary on open
$('#repo-dd').addEventListener('toggle',function(){
  if(!this.open) return;
  const r=this.querySelector('summary').getBoundingClientRect(), menu=this.querySelector('.repodd-menu');
  menu.style.top=Math.round(r.bottom+4)+'px';
  menu.style.left=Math.round(Math.max(6, Math.min(r.right-menu.offsetWidth, window.innerWidth-menu.offsetWidth-6)))+'px';
});
// native <details> doesn't close on outside-click — do it ourselves
document.addEventListener('click',e=>{ const dd=$('#repo-dd'); if(dd && dd.open && !dd.contains(e.target)) dd.open=false; });
document.addEventListener('keydown',e=>{ if(e.key==='Escape'){ const dd=$('#repo-dd'); if(dd) dd.open=false; } });

// theme switcher (gruvbox / rose pine / everforest — all dark)
document.querySelectorAll('#theme-toggle a').forEach(a=>a.addEventListener('click',()=>applyTheme(a.dataset.t)));

function init(){
  $('#who').textContent=DATA.user;
  if(DATA.light) $('#lightbanner').innerHTML='<div class="lightbanner"><b>light mode</b> — public data only · traffic (views / clones / referrers) and watcher counts need a token</div>';
  if(DATA.avatar){ const a=$('#avatar'); a.src=DATA.avatar; a.hidden=false; }
  topRepos(10).forEach(n=>chartSel.add(n));   // per-repo chart starts at the top 10 by views
  const totalStars=DATA.repos.filter(r=>!r.fork).reduce((s,r)=>s+(r.stars||0),0);
  $('#ustats').innerHTML=`<span style="color:var(--amber)">&#9733;</span> <b>${fmt(totalStars)}</b> stars &nbsp;·&nbsp; <b>${fmt(DATA.followers||0)}</b> followers`;
  $('#meta').textContent=`generated ${DATA.generated} · ${DATA.repos.length} repos · GitHub serves a rolling ${DATA.window_days}-day window`;
  if(DATA.skipped && DATA.skipped.length){
    $('#skip').innerHTML='<div class="skip">skipped (no access): '+DATA.skipped.map(s=>esc(s.name)).join(', ')+'</div>';
  }
  $('#foot').innerHTML=`gh-traffic · single self-contained file · no token stored here · charts are inline SVG (offline).<br>`+
    `Trend &#9650;/&#9660; compares the recent half of the shown window against the prior half (e.g. the last 7 days vs the 7 before); it shows “NA” when there's no prior baseline (it grew from zero or there's too little data). `+
    (DATA.history_enabled?`Daily series is merged into a local history store, so it can extend past 14 days over time. `:``)+
    `Referrers are GitHub's 14-day aggregate (no per-day data). `+
    `Unique-visitor/cloner totals are summed per repo and overcount anyone who visited several repos.`;
  applyTheme('gruvbox');  // sets CSS vars + paints palette swatches + renders
}
init();
</script>
</body>
</html>
"""


# ───────────────────────────── main ───────────────────────────────────────
def banner() -> str:
    """Small ASCII title shown on every run."""
    art = ("  ┌─┐┬ ┬   ┌┬┐┬─┐┌─┐┌─┐┌─┐┬┌─┐\n"
           "  │ ┬├─┤    │ ├┬┘├─┤├┤ ├┤ ││  \n"
           "  └─┘┴ ┴    ┴ ┴└─┴ ┴└  └  ┴└─┘")
    sub = "  GitHub Traffic Board · by HANCORE-linux"
    if sys.stdout.isatty():
        return f"\033[38;5;108m{art}\033[0m\n\033[2m{sub}\033[0m\n"
    return f"{art}\n{sub}\n"


def main() -> None:
    print(banner())
    ap = argparse.ArgumentParser(description="Local GitHub traffic dashboard (cliamp look).")
    ap.add_argument("--out", default=str(DATA_DIR / "report.html"),
                    help="output HTML path (default: ~/gh-traffic/report.html)")
    ap.add_argument("--no-open", action="store_true", help="don't open the report in a browser")
    ap.add_argument("--no-history", action="store_true", help="don't read/write the local history store")
    ap.add_argument("--save-token", action="store_true", help="save the entered token to the XDG config dir (0600)")
    ap.add_argument("--repos", default="", help="comma-separated subset of repo names")
    ap.add_argument("--workers", type=int, default=8, help="parallel fetch workers (default: 8)")
    ap.add_argument("--no-thumbs", action="store_true", help="skip repo preview images (faster; all placeholders)")
    ap.add_argument("--refresh-thumbs", action="store_true", help="re-fetch preview images, ignoring the ETag cache")
    ap.add_argument("--public", nargs="?", const="", default=None, metavar="USER",
                    help="light mode: public data for USER (any username), no token, no traffic")
    args = ap.parse_args()

    want_thumbs = not args.no_thumbs
    if want_thumbs and not MAGICK:
        print("  note: ImageMagick (magick/convert) not found — preview images skipped (placeholders shown). "
              "Install imagemagick for theme previews, or use --no-thumbs to silence this.")
        want_thumbs = False

    # ── choose mode: full (token → traffic) vs light (username → public only) ──
    light = args.public is not None
    if not light and not _token_available() and sys.stdin.isatty():
        print("  [F] full   — your repos' traffic · needs a GitHub token")
        print("  [l] light  — any user's public data · no token")
        ans = input("  choose [F/l]: ").strip().lower()
        if ans.startswith("l"):
            light = True
            args.public = ""   # trigger the username prompt below

    if light:
        username = args.public or input("GitHub username: ").strip()
        if not username:
            sys.exit("No username given.")
        gh = GitHub()  # public, unauthenticated API
        print(f"Light mode — public data only (no token, no traffic) for: {username}")
        print("  note: the unauthenticated GitHub API allows ~60 requests/hour. Many repos + "
              "thumbnails can hit that limit; thumbnails are cached, so just re-run to fill gaps.")
        user, avatar_url, followers = gh.public_user(username)
        repos = gh.public_repos(username)
        if args.repos:
            wanted = {r.strip() for r in args.repos.split(",") if r.strip()}
            repos = [r for r in repos if r.get("name") in wanted]
        avatar = fetch_avatar(avatar_url) if not args.no_thumbs else None
        print(f"Building light report for {len(repos)} public repos…")
        collected = collect_light(gh, username, repos, want_thumbs, args.refresh_thumbs)
        skipped, history_enabled = [], False
        authored_issues, authored_prs = gh.authored_counts(username)
    else:
        token, source = load_token(args.save_token)
        if source != "prompt":
            where = "$GITHUB_TOKEN" if source == "env" else str(TOKEN_FILE)
            print(f"Using token from {where} (not a prompt).")
        gh = GitHub(token)
        user, avatar_url, followers = gh.whoami(source)
        print(f"User: {user}")
        repos = gh.owned_repos()
        if args.repos:
            wanted = {r.strip() for r in args.repos.split(",") if r.strip()}
            repos = [r for r in repos if r.get("name") in wanted]
        avatar = fetch_avatar(avatar_url) if not args.no_thumbs else None  # avatar needs no ImageMagick
        print(f"Fetching traffic for {len(repos)} repos" + (" + preview thumbnails (first run downloads them)…" if want_thumbs else "…"))
        collected, skipped = collect(gh, user, repos, args.workers, want_thumbs, args.refresh_thumbs)
        if skipped:
            print(f"  skipped {len(skipped)} (no access): " + ", ".join(s["name"] for s in skipped))
        authored_issues, authored_prs = gh.authored_counts(user)
        history_enabled = not args.no_history
        if history_enabled:
            store = merge_history(collected)
            attach_history(collected, store)

    data = {
        "user": user,
        "avatar": avatar,
        "followers": followers,
        "authored_issues": authored_issues,
        "authored_prs": authored_prs,
        "light": light,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": 14,
        "history_enabled": history_enabled,
        "repos": collected,
        "skipped": skipped,
    }
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    render(data, out)
    print(f"Report: {out}")
    if not args.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nAborted.")
