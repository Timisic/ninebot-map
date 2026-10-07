# Destination names and themes

A user opens the destination list, names a place and switches themes while retaining their working view.

## Sub-features

- `place-select` highlights routes ending at the selected place. Named places retain pins. Unnamed places show only a temporary cue, even when selected.
- `place-cue` shows the selected place name and pale disk for three seconds. Repeat selection and Locate renew the cue. Rendering and same-dataset refresh preserve the original deadline. Expiration keeps selection, draft and view.
- `cue-cleanup` clears the cue on explicit deselection, removed destination, changed dataset and page teardown. Reduced motion uses a static cue.
- `local-font` loads the actual local Smiley Sans face and preserves 11px statistics.
- `place-stable` keeps the same selection on repeat click, map click and zoom.
- `drawer-retain` preserves draft and selection on close/reopen without shrinking the list.
- `label-save` retains a saved name after a page reload. Named pins are independent of the list's first 100 places.
- `place-merge` explicitly combines source and target historical memberships. Renaming and clearing a name do not undo the merge. Equal names alone remain separate.
- `activity-days` counts unique riding dates across every named badminton venue. Same-day returns and multiple venues count once.
- `nature-duration` displays summed known parking seconds as hours and minutes. Missing intervals remain unknown.
- `mobile-panel` bounds the dock at 260px or 34dvh, keeps day and nature statistics visible, and exposes statistics help in the heading.
- `theme-select` chooses system, dark and light themes.
- `system-theme` responds to system changes only while system is selected.
- `theme-retain` preserves an unsaved name and map view during a switch.

## How to get to it (user POV)

- Choose the places toggle, a list item or a map marker.
- Select a place, choose `#edit-place`, edit the name and submit the form.
- Open `#theme-options` and choose a `[data-theme-preference]` button.

## Driving it with Playwright

Preconditions:

- `npm run verify:doctor` succeeds.
- Use a fresh context with the synthetic map fixture.

Run `npm run verify -- --suite map`. The harness opens `#toggle-places`, selects `.place-button`, clicks `#edit-place`, fills `#place-label`, saves through `#label-form` and reloads to read the persisted name. It opens `#theme-toggle` and chooses a theme while a name draft is unsaved, verifies the draft and view remain, and checks persisted theme after reload. It changes the system color scheme, verifies the default follows it, confirms a manual choice overrides it, then returns to system. The blocked-storage path must still allow theme switching within the current page. After the font loads, measure all three selected theme choices at 1440px, 390px and 320px. Require the glyph center to match the 44px hit target and each selected row to stay within the menu. Exercise the cue through editing, repeat selection, rapid different selection, expiration, Locate and cancellation. The refresh suite also checks same-dataset continuity, missing destinations and dataset switches. Run `npm run verify -- --suite static` to require the local font response at its versioned nested path, matching original bytes and an exported OFL license.

Use `#merge-place`, `#merge-target`, and `#merge-form` to merge two places, then rename, reload, and clear the name. Read the resulting counts and persistent marker membership. The map harness checks a named place outside the first 100 list entries, distinct places with equal names, a same-day badminton return, and exact-seconds nature formatting. Retain screenshots at 390×844, 320×720, 640×360, and 844×390. Check `#places-panel` bounds, `.nature-stat` visibility, and the heading's statistics disclosure. Shared parking fixtures run through both the Python and model suites.

## Gotchas

- General destination counts mean observed track endpoints. Badminton row counts use unique riding days. Neither confirms a person was present.
- Stored names are keyed by dataset, coordinate interpretation and historical ride membership.
- A test of saved names does not prove preservation of an unsaved draft; both actions are exercised.
