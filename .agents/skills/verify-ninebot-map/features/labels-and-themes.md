# Destination names and themes

A user opens the destination list, names a place and switches themes while retaining their working view.

## Sub-features

- `place-select` highlights routes ending at a selected place.
- `place-stable` keeps the same selection on repeat click, map click and zoom.
- `drawer-retain` preserves draft and selection on close/reopen without shrinking the list.
- `label-save` retains a saved name after a page reload.
- `theme-toggle` switches dark and light themes.
- `theme-retain` preserves an unsaved name and map view during a switch.

## How to get to it (user POV)

- Choose the places toggle, a list item or a map marker.
- Select a place, choose `#edit-place`, edit the name and submit the form.
- Choose the toolbar theme button.

## Driving it with Playwright

Preconditions:

- `npm run verify:doctor` succeeds.
- Use a fresh context with the synthetic map fixture.

Run `npm run verify -- --suite map`. The harness opens `#toggle-places`, selects `.place-button`, clicks `#edit-place`, fills `#place-label`, saves through `#label-form` and reloads to read the persisted name. It also switches `#theme-toggle` while a name draft is unsaved, verifies the draft and view remain, and checks persisted theme after reload. The blocked-storage path must still allow theme switching within the current page.

## Gotchas

- Destination counts mean observed track endpoints, not confirmed visits.
- Stored names are keyed by dataset, coordinate interpretation and historical ride membership.
- A test of saved names does not prove preservation of an unsaved draft; both actions are exercised.
