# Import and date filtering

A user opens a local map, imports a Ride Dataset v1 file and filters map rides without changing all-history totals.

## Sub-features

- `import-page` opens an empty import page.
- `import-file` loads a user-selected standard dataset.
- `launch-dataset` opens a dataset supplied on the CLI.
- `date-range` filters the visible routes inclusively.
- `invalid-import` retains the previous valid map.

## How to get to it (user POV)

- Run `./run map`, then choose Import or drop a file.
- Run `./run map --dataset tests/fixtures/synthetic-map.json --port 0 --no-open`.
- Expand the date panel, set dates, or choose all dates.

## Driving it with Playwright

Preconditions:

- `npm run verify:doctor` succeeds.
- Use only `tests/fixtures/synthetic-map.json` and generated synthetic datasets.

Run `npm run verify -- --suite map`. Its harness starts the normal CLI, imports through `#file`, sets `#from`, reads `#visible-stat` and `#history-stat`, clears the range, then imports malformed JSON. Require twelve fixture rides initially, three visible rides after the fixture filter, unchanged twelve history rides, and retention of the prior map after invalid import.

Read the map suite log. UI evidence can be requested through the wrapper's output directory.

## Gotchas

- `--latest` uses the user's selected local archive; it is not part of the default synthetic run.
- A range filter never expands the dataset's saved map scope.
- Existing labels and browser state must not come from the user's actual browser profile.
