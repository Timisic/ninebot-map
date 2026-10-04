# Refresh a running map

A user keeps the map open while a local download updates the standard dataset; the page refreshes without losing their saved working state.

## Sub-features

- `valid-update` reads a new valid dataset through the running server.
- `retain-controls` preserves dates, coordinates, names and view.
- `invalid-update` retains the previous valid dataset.
- `manual-import` keeps a manually imported file in control of the page.

## How to get to it (user POV)

- Open `./run map --dataset <file>` and replace that local file with valid standard data.
- Return an already open page to the foreground after `./run cloud pull`.
- Open `./run cloud map` to download and display the latest real archive when authorized.

## Driving it with Playwright

Preconditions:

- `npm run verify:doctor` succeeds.
- Let the harness create its scratch dataset and server; do not reuse a user map.

Run `npm run verify -- --suite refresh`. The harness verifies the loopback HTTP summary and ETag, starts with one ride, applies date and coordinate controls, saves a synthetic name, and atomically replaces its dataset with two rides. Bringing the page forward must show two history rides while retaining one filtered map ride, the dates, coordinates, name and view. It then replaces the file with invalid data and exercises manual import ownership.

Read the refresh proof and before/after screenshots. Require process termination, closed socket and removed scratch data after cleanup while proof files still exist.

## Gotchas

- This proves refresh after local file replacement; it does not prove a real cloud download.
- Invalid data may be rejected by the server before reaching the browser.
- A manually imported file stops automatic following until the page is reopened.
