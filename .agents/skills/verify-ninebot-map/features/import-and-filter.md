# Dataset loading and Along navigation

A user opens a local map and sees the configured dataset with visible-map and all-history totals next to the route legend.

## Sub-features

- `read-only-page` has no file picker, drop importer or upload endpoint.
- `launch-dataset` opens a dataset supplied on the CLI.
- `activity-navigation` displays Riding ｜ Running and a short Running hint.
- `quiet-statistics` uses the existing legend's 11px text without an extra frame.
- `invalid-replacement` retains the previous valid map.

## How to get to it (user POV)

Run `./run map --dataset tests/fixtures/synthetic-map.json --port 0 --no-open`.

## Driving it with Playwright

Run `npm run verify:doctor`, then `npm run verify -- --suite map` in a fresh context. Require twelve fixture rides, unchanged history totals, an Along browser title, activity navigation at 390px and 320px, and no date controls. Click `#running` and read “正在running中...” in `#inline-hint`. Replace the owned synthetic dataset with malformed JSON and require the previous map to remain.

## Gotchas

The dataset's saved map scope still limits the visible routes. Removing the page's date controls does not expand that scope. Use synthetic fixtures and a new browser context instead of the user's actual profile.
