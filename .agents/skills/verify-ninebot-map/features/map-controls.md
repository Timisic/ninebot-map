# Wheel and coordinate controls

A user zooms around the pointer and toggles road tiles over unchanged raw coordinates.

## Sub-features

- `wheel-continuous` keeps fractional zoom moving through sustained input.
- `wheel-reverse` cancels the previous target immediately on reversal.
- `wheel-boundary` respects minimum and maximum zoom.
- `wheel-anchor` retains the geographic point under the pointer.
- `wheel-cancel` stops pending zoom on external view changes, drag, resize and teardown.
- `wheel-motion` applies the target directly with reduced motion.
- `wheel-alignment` checks Canvas route pixels and marker positions during fractional zoom.
- `basemap-continuity` retains visible fallback tiles while delayed new tiles load across fractional zoom levels.
- `route-visibility` checks one, two and six routes in both themes at zooms 10, 13 and 16.
- `raw-coordinate-display` ignores legacy CRS controls and keeps points unchanged.
- `basemap-toggle` enables or removes road tiles without moving routes.

## How to get to it (user POV)

- Scroll or pinch over the map.
- Use zoom buttons or keyboard input.
- Open the bottom-right layers menu and toggle the road basemap or passage grid.

## Driving it with Playwright

Preconditions:

- `npm run verify:doctor` succeeds.
- Use an isolated browser with the bundled production Leaflet and wheel handler.

Run `npm run verify -- --suite wheel`. Require raw pixel, line, page and pinch deltas at device pixel ratios one and two to reach the same expected zoom. Inspect fractional progress, fixed anchor, reversal, limits, cancellation, reduced motion and cleanup assertions. Run `npm run verify -- --suite map` for `#basemap`, `#show-grid` and `#theme-toggle`. The UI harness asserts exactly two switches, enables mocked tiles without a coordinate selector, checks unchanged marker positions and removes the online layer.

## Gotchas

- Synthetic wheel events prove handler behavior, not physical hardware feel.
- Mocked tile availability does not prove live OpenStreetMap connectivity or image sharpness.
- Road preview does not verify the source coordinate system.
- Button and keyboard affordances are separate entry points; report them unverified unless the run exercises them.

The map suite delays synthetic tile responses by 160 ms and samples loaded images covering the map center during forward and reversed wheel input. The wheel suite composites route pixels against each offline theme and requires contrast of at least 3:1 for single and repeated routes. These controlled backgrounds do not establish contrast over every live tile color.
