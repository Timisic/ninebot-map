# Ninebot Map verification map

Use a fresh browser profile, synthetic fixtures and a random loopback port for each run. The helper starts and closes its own instances. Evidence survives cleanup under `work/verification/`.

| Feature | Recipe | Verification command |
| --- | --- | --- |
| Dataset loading and date range | [Load and filter](import-and-filter.md) | `npm run verify -- --suite map` |
| Destination names and themes | [Labels and themes](labels-and-themes.md) | `npm run verify -- --suite map` |
| Wheel input and coordinate interpretation | [Map controls](map-controls.md) | `npm run verify -- --suite wheel` and `--suite map` |
| Map update after local data replacement | [Data refresh](data-refresh.md) | `npm run verify -- --suite refresh` |
| Collection, merge and public image boundaries | [Cloud boundaries](cloud-boundaries.md) | `npm run verify -- --suite python` |

Start with `npm run verify:doctor`. Read the recipe before driving its surface. A skipped cloud entry point is not verified by passing a local UI test.
