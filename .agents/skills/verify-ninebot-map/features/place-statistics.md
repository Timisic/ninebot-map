# Place statistics

## Sub-features

Read [the statistics contract](../../../../docs/place-statistics.md). Run the doctor, model and map suites. Existing shared stop-duration fixtures establish cross-midnight, incomplete chronology, overlap, missing tracks and 24-hour boundaries for both JS and Python.

The model tests use public geographic fixtures: two nearby campus points must separate, unrelated clusters must retain their members, and reversing input must retain identity. South/northeast/north park endpoints union into one duration; passing routes, short stops, outside road lanes and residential areas do not count. Dates follow arrival ride dates; unknown/open stops stay unknown. Names, merges and overlapping entrance catchments must not increase the total. Unnamed outside gates without positive public-access evidence stay uncertain, and 15-metre outer-boundary tolerance must retain small GPS offsets without buffering across a shared campus boundary. Raw coordinates and history metrics remain unchanged.

## How to get to it (user POV)

Open the local map and read the top-left natural parking total, then open 常去地点 for per-place details.

## Driving it with Playwright

The browser map suite checks `#nature-total` between `#update-map` and `#badminton-stat`, its activity name and duration in visible copy, title and accessible label, and toolbar containment in both themes at desktop/mobile widths. Require no persistent implementation or verification copy, substitute badges or leftover explanation-row spacing in the main view, following [the main-view copy rule](../../../../AGENTS.md#main-view-copy). Existing basemap and label tests remain required. Use synthetic fixtures for retained regression screenshots. For a separately authorized real-data review, keep processing local and cover the entire map/precise location surface before retaining any screenshot; do not upload raw trajectories or enable external tile requests.

## Gotchas

Parking time estimates vehicle absence between adjacent rides, not a person’s confirmed park activity. Unverified source CRS and incomplete public geometry remain limitations.
