# Destination names and themes

A user opens the destination list, names a place and switches themes while retaining their working view.

## Sub-features

- `place-select` highlights routes ending at the selected place. Named places retain pins. Unnamed places show only a temporary cue, even when selected.
- `place-cue` shows the selected place name and pale disk for three seconds. Local editable maps renew the cue on repeat selection and Locate. Rendering and same-dataset refresh preserve the original deadline. Expiration keeps selection, draft and view.
- `cue-cleanup` clears the cue on explicit deselection, removed destination, changed dataset and page teardown. Reduced motion uses a static cue.
- `local-font` loads the actual local Smiley Sans face and preserves 11px statistics.
- `place-stable` keeps selection on repeat click, marker click, map background, controls, drag and zoom for both local and shared maps. `#clear-selection` clears the selection. A same-dataset refresh keeps an in-progress name draft.
- `drawer-retain` preserves draft and selection on close/reopen without shrinking the list.
- `shared-places` shows the detail box and rename control on a shared map. Merge stays hidden when the served public map includes `place_annotations`. Submitting `#label-form` posts the merged ride ids to `POST /api/place-names`. The server writes `place-names.json` and projects labels into the served `dataset.json`. A generation file at `prepared/<generation>/dataset.json` uses `prepared/place-names.json`. Other datasets keep the ledger in the same directory. The dataset file and `updated_at` stay unchanged, and the served ETag changes. A second open page polls that document with HEAD on focus, when the page becomes visible, and every 60 seconds. That page sends HEAD and GET for `dataset.json`. Old browser labels stay stored and do not override served names. An empty `place_annotations` object on a public file serves no published names and an empty merge list. Ledger overrides still appear in those served labels. A static file host has no ledger, so that empty object leaves the places unnamed. A static file host that rejects POST shows `名称没有保存，请重试。` and leaves the visible name unchanged.
- `label-save` retains a saved name after a page reload. Named pins are independent of the list's first 100 places.
- `place-merge` explicitly combines source and target historical memberships. Renaming and clearing a name include temporarily absent historical members and do not undo the merge. Equal names alone remain separate.
- `activity-days` counts unique riding dates across every named badminton venue. `#badminton-stat` shows `badmintonDays` from the existing `select`. Same-day returns and multiple venues count once. Names containing 🏸 use the racket in both the list and map. Clearing the name returns the count to `0 次`.
- `nature-duration` applies when a member lies in the park parking set, or when the custom name contains 奥森南门 after whitespace removal. 🏸 takes precedence. The place card sums known seconds before formatting hours and minutes. All-unknown coverage shows “暂无停留数据”. Known time with unknown stops adds “部分估算”. Uncertain stops with no known time show “停车位置待确认”. The toolbar total shows the known duration, “暂无停留数据”, or “0 h 0 min”. The accessible description reports known and unknown counts.
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

Run `npm run verify -- --suite map`. The harness opens `#toggle-places`, selects `.place-button`, clicks `#edit-place`, fills `#place-label`, saves through `#label-form` and reloads to read the persisted name. It opens `#theme-toggle` and chooses a theme while a name draft is unsaved, verifies the draft and view remain, and checks persisted theme after reload. It changes the system color scheme, verifies the default follows it, confirms a manual choice overrides it, then returns to system. The blocked-storage path must still allow theme switching within the current page. It must also allow a name save on the map server. The success note is `已保存，其他打开此地图的人会看到。` A seeded legacy label does not appear. Name that place through the form. After the font loads, measure all three selected theme choices at 1440px, 390px and 320px. Require the glyph center to match the 44px hit target and each selected row to stay within the menu. Exercise the cue through editing, repeat selection, rapid different selection, expiration, Locate and cancellation. The refresh suite also checks same-dataset continuity, missing destinations and dataset switches. Run `npm run verify -- --suite refresh` with a second page opened before the save. After focus, that page shows the saved name. The scratch `dataset.json` bytes stay the same. Run `npm run verify -- --suite model` and require the same-day `select` badminton count to be `1`, then `0` after the name is cleared. Run `npm run verify -- --suite python` and require `test_two_clients_share_a_place_name_without_rewriting_the_dataset` and `test_place_names_are_shared_without_an_update_token` to pass. Run `npm run verify -- --suite static` to require the local font response at its versioned nested path, matching original bytes and an exported OFL license.

Use `#merge-place`, `#merge-target`, and `#merge-form` to merge two places, then rename, reload, and clear the name. Read the resulting counts and persistent marker membership. The map harness checks a named place outside the first 100 list entries, distinct places with equal names, a same-day badminton return that shows `1 次` in `#badminton-stat` and `0 次` after the name is cleared, and exact-seconds nature formatting. Retain screenshots at 390×844, 320×720, 640×360, and 844×390. Check `#places-panel` bounds, `.nature-stat` visibility, and the heading's statistics disclosure. Assert the all-unknown nature row text, not only its geometry. Shared parking fixtures and absent-member merge/rename cases run through the Python and model suites as applicable.

## Gotchas

- General destination counts mean observed track endpoints. Badminton row counts use unique riding days. Neither confirms a person was present.
- Saved names live in `place-names.json`. A generation dataset under `prepared/` shares `prepared/place-names.json`. Other datasets keep the ledger in the same directory. Merge records stay in the browser and follow the dataset, coordinate interpretation and clustering setting. Theme stays with the browser origin.
- A test of saved names does not prove preservation of an unsaved draft; both actions are exercised.

Run `npm run verify -- --suite static` for three fresh contexts at 1440px, 390px and 320px with shared synthetic names, merged endpoints and badminton days. Inject conflicting localStorage into one context and reload. Require the same shared result and unchanged stored values. Shared maps show the detail box and the rename control. Merge stays hidden. Repeat click, marker click and map background keep the selection. `#clear-selection` restores the routes. Refresh applies revised names. Publish empty annotations and require unnamed places. A rejected POST shows `名称没有保存，请重试。` and leaves the visible name unchanged. Measure timestamp and update-button centers within one pixel in idle, queued and failed states. Retain `shared-places.json` and the three screenshots. The Python suite also proves private reinstallation and publication preserve configured annotations.
