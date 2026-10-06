# Refresh a running map

A user keeps the map open while local data changes, or requests a public update through GitHub Actions. The page retains their working state.

## Sub-features

- `valid-update` reads a new valid dataset through the running server.
- `retain-controls` preserves grid, saved names, selection, draft, theme and view.
- `retain-cue` keeps a live cue and its original monotonic deadline through same-dataset replacement and provisional selection clearing. Expiration leaves editing and view unchanged.
- `clear-cue` removes the cue when its destination disappears or dataset identity changes.
- `invalid-update` retains the previous valid dataset.
- `public-update` waits for workflow success and newly collected data.
- `shared-cooldown` displays the same activity hint for a server 429 and repeated clicks.
- `update-failure` retains the map when dispatch is rejected or the service is unavailable.
- `local-unavailable` disables the public update button on a local 404 without a page error.

## How to get to it (user POV)

Open `./run map --dataset <file>`, replace that local file with standard data, and return the page to the foreground. A configured public site exposes its update button at the upper left.

## Driving it with Playwright

Run `npm run verify:doctor`, then `npm run verify -- --suite refresh`. The harness owns a scratch dataset, local server and fresh browser context. It confirms GET summary and HEAD ETag, starts with one ride, saves a synthetic place name, and checks grid and view retention after replacing the dataset with two rides. An invalid replacement must preserve both rides.

The public-update checks mock the same-origin API contract while using the real local dataset server. An accepted request progresses through queued, running and succeeded. The page must wait for data collected after that request before reporting success. It then reads three rides while retaining selection, an unsaved label draft, grid, theme and view. The compact timestamp omits the year visually and retains a full datetime and title. Success uses a visually hidden aria-live message. A server 429 and subsequent clicks display “正在Riding中...” in the same hint as Running. Dispatch rejection and unavailable responses preserve the visible map.

Read `refresh.json` and the before/after screenshots. Require owned process termination, a closed socket and removed scratch data while evidence remains.

## Gotchas

API fixtures prove browser behavior against the stated contract. They do not prove real GitHub dispatch, a live ninebot session, or public rate-limit enforcement. Those entry points need separately authorized cloud evidence.
