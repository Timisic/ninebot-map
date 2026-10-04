---
name: verify-ninebot-map
description: Verify this repository's local Ninebot Map UI, CLI, refresh, and cloud boundaries using synthetic fixtures, retained evidence, and owned-process cleanup. Use after map, collector, deployment, or project-layout changes.
---

# Verify Ninebot Map

Run from this repository's root. This skill belongs to `.agents/skills/`; keep it project-local. Read [the feature index](features/README.md), then the feature file matching the change.

## Launch

Use the repository's installed `.venv/bin/python`, Node, and Playwright. If dependencies are missing, run `./scripts/setup.sh` and `npm ci`. Local browser checks default to installed Chrome. Set `PLAYWRIGHT_CHANNEL=chromium` to use Playwright's bundled Chromium after installing it with `npx playwright install chromium`.

The existing browser harnesses launch `./run map --dataset <synthetic-file> --port 0 --no-open`. Read the emitted loopback URL; the allocated port differs per run. The refresh harness creates its dataset in a unique ignored scratch directory. It owns the server and browser it starts.

## Doctor

Run `npm run verify:doctor`. Require exit code zero before browser verification. This checks Python imports, Node, Playwright and the requested browser without using an account or Ninebot API.

The refresh harness also performs a read-only HTTP doctor on its owned instance before driving the browser. It confirms the dataset summary and the GET/HEAD ETag against its seeded fixture and records the process ID and allocated URL. An unrelated user's open map is outside this run's ownership.

## Drive

- `npm run verify:smoke` checks project layout and the real local map refresh path.
- `npm run verify` runs project structure, Python, model, browser, wheel and refresh suites.
- `npm run verify -- --suite map` covers import, date filtering, labels, themes and basemap behavior.
- `npm run verify -- --suite wheel` covers production wheel handling at two device pixel ratios.
- `npm run verify -- --suite refresh` covers valid updates, preserved controls, invalid replacement and manual import ownership.
- `npm run verify -- --suite python` covers collector, local server, scheduler and cloud behavior with synthetic adapters.
- `npm run verify -- --suite model` covers route, grid and destination calculations.

Use existing selectors and actions in the harnesses. The refresh recipe fills `#from` and `#to`, chooses `#crs`, saves a name through `#label-form`, replaces its synthetic source file, and brings the page to the foreground. It reads `#history-stat`, `#visible-stat`, the controls and the saved name afterward.

## Evidence

Each wrapper invocation retains its report and suite logs under a unique `work/verification/` directory. Set `--output <directory>` to choose another evidence location. Refresh proof records the launch, HTTP doctor, user actions, visible results and cleanup, with screenshots before and after the update.

Read `report.json` and the selected suite's evidence after the command exits. Assert observable state, not a success message alone. Wheel evidence uses synthetic DOM events and does not establish physical trackpad feel. Basemap UI tests fulfill tile requests locally and do not establish live provider availability. Cloud unit tests do not establish a live account session, GitHub permissions or new Ninebot data.

Routine verification uses synthetic data and browser request isolation. Real cloud downloads, credential changes and publication follow the current user's specific task authorization. Describe any unexercised real entry point as unverified.

## Cleanup

The harness closes its browser and terminates only its spawned server. Refresh proof verifies that the owned server exits and its socket stops answering, then removes the scratch dataset. Evidence remains in its output directory. Check the cleanup record and that screenshots/logs still exist after teardown. If a run fails, inspect its retained log and close only processes recorded as owned by that run.

## Helpers

`scripts/verify.mjs` is the executable wrapper behind the npm commands. `scripts/check-project.py` checks layout, links, skill shape and tracked runtime-file boundaries. The wrapper reuses `scripts/verify-map.mjs`, `scripts/verify-wheel.mjs` and `scripts/verify-auto-sync.mjs`; add feature coverage there rather than building another harness.

Keep this map aligned with actual entry points. Use `pstack-personal:maintain-verification-skill` when asked to audit it after feature changes.
