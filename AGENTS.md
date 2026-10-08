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

## Plugin design

### Look

- Colors come only from the Omarchy theme, passed in by `Panel.qml`: `Color.popups.text`,
  `Color.popups.background`, `Color.accent`, `Color.urgent`, `Color.tooltip.*`, plus
  `Style.cornerRadius` and `Style.font.family`. Shades are alpha steps of these colors
  (`rgba(color, a)`); `dim` is the text color darkened by 1.4.
- Alpha scale: 0.04 rest, 0.08 hover, 0.12 dividers, 0.18 selected, 0.4 borders. Notices:
  neutral 0.06; errors urgent 0.10 with a 2 px urgent bar; warnings accent 0.10 with a
  2 px accent bar.
- Type scale: views number 26, clones number 16, title 14 bold, body 12, hints and
  notices 11, captions 10. The meta line is 10 bold uppercase with 1.2 letter spacing.
- A number's label sits to its right on the same baseline with a 6 px gap
  (`10,667 views`, `6,639 clones`), never below it.
- Controls are 28 px high: chips (corner radius, 1 px border unless selected), square
  icon chips, text fields 262 px wide. Header actions, left to right: repos pill,
  Traffic/Light switch, options, refresh.
- Icons are Nerd Font glyphs in the theme font: eye for Traffic, person for Light, key
  for setup. The bar shows eye + views, or star + stars in Light mode.

### Layout

- Fixed grid: 528 px content with 14 px padding; repository names 204 px; 14 day cells
  of 11 px with 3 px gaps; views column 54 px, clones column 43 px; matrix rows 22 px.
- Top to bottom: header; mode-specific notices (confirmation, error, skipped
  repositories, request warning); views row (46 px, accent bars up to 44 px) and clones
  row (26 px, bars at text color 0.5) with the trend on the right and the first and last
  day below; the repository matrix (heat levels from 1, 4, 16 and 64 views as accent
  0.32, 0.52, 0.75 and 1.0, empty cells text color 0.06, less/more legend, hover
  tooltip);
  referrers (top 3); footer with exports.
- Lists show the top 16, then *Show 36 more*, then *Show all*.

### Behavior

- Nothing runs in the background. Data loads on refresh: the button, `r`, or a
  middle-click on the bar icon. From 200 API requests on, the panel asks first:
  *Load anyway*, *Choose repositories*, *Cancel*.
- Traffic covers only the user's own repositories, without forks. The plugin shows no
  preview images, pull requests, watchers or fork counts.
- Light mode keeps up to 10 users, each with its own cached data.
- Options: Mode; Repositories (All or Selected, with filter, *Select shown*, *Clear*,
  10 visible rows, a lock on private ones); Bar widget (Icon, Text, Icon and text;
  vertical bars always show the icon); Token. Confirmations such as "Token saved" or
  "Added octocat" disappear after 4 s.
- The bar icon dims while loading, turns urgent on errors and accent on a spike (the
  last day at least twice the median).
- Check layout changes by rendering the panel offscreen (`QT_QPA_PLATFORM=offscreen`)
  for truncated, overflowing or overlapping text before shipping.
