# Wheel and coordinate controls

A user zooms around the pointer and chooses coordinate interpretation before enabling a road basemap.

## Sub-features

- `wheel-burst` limits a continuous wheel burst to one zoom level.
- `wheel-reverse` responds to a fresh reversed gesture.
- `wheel-boundary` respects minimum and maximum zoom.
- `coordinate-select` changes preview interpretation locally.
- `basemap-gate` enables a basemap only for a selected usable interpretation.

## How to get to it (user POV)

- Scroll or pinch over the map.
- Use zoom buttons or keyboard input.
- Open settings, choose coordinates, then toggle the road basemap.

## Driving it with Playwright

Preconditions:

- `npm run verify:doctor` succeeds.
- Use an isolated browser with the bundled production Leaflet and wheel handler.

Run `npm run verify -- --suite wheel`. Require the raw delta traces at device pixel ratios one and two to match the asserted zoom results. Run `npm run verify -- --suite map` for `#crs`, `#basemap` and `#theme-toggle`. The UI harness keeps unverified coordinates gated, changes the interpretation, enables mocked tiles, checks route pixels and removes the online layer.

## Gotchas

- Synthetic wheel events prove handler behavior, not physical hardware feel.
- Mocked tile availability does not prove live OpenStreetMap connectivity or image sharpness.
- Selecting a coordinate interpretation does not verify the source coordinate system.
- Button and keyboard affordances are separate entry points; report them unverified unless the run exercises them.
