# AGENTS.md

One repo, two uses: `gh_traffic.py` is the standalone script and also the data helper
of the Omarchy bar plugin (`manifest.json` at the root, QML in `plugin/`).

## Rules

- `gh_traffic.py` stays one file on the Python standard library only. ImageMagick is
  optional (thumbnails). The token goes only to api.github.com, never into HTML or logs.
- Route every GitHub call through `GitHub.get` or `GitHub.get_raw`, so requests stay
  paced (`REQUESTS_PER_MINUTE`) and failures are retried.
- The panel runs the script with `--json --confirm-above N --repos LIST`,
  `--json --public USER` and `--from-json FILE --out FILE`. Keep that JSON compatible
  with `plugin/Model.js` and `plugin/Panel.qml`.
- Every QML `Text` uses `textFormat: Text.PlainText`. Repository names and API messages
  are untrusted, and the marketplace review checks it. UI text is English.
- Exports leave private repositories out unless *Include private* is on.
- Bump `"version"` in `manifest.json` with every user-visible change, and run
  `omarchy-plugin-validate .` before pushing.
- Screenshots for the README or releases use fictional demo data only (`make_demo.py`,
  demo snapshots). Real snapshots contain private repository names.
- Commit with the GitHub noreply address and without AI co-author trailers.
