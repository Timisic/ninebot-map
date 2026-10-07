# Collection and cloud boundaries

A user retains historical rides during collection and merging, and publishes a static track image and an allowlisted website dataset separately from private archives.

## Sub-features

- `archive-retain` preserves usable snapshots on a failed refresh.
- `geometry-retain` keeps better saved geometry during cloud merging.
- `due-gate` respects success time, retries and disabled state.
- `image-publish` changes only the authorized PNG and README block.
- `site-publish` publishes public map JSON through the restricted receiver, validates its receipt, and preserves the original collection timestamp on publish-only runs.
- `parking-export` exports derived stop seconds while keeping precise ride timestamps private.
- `bundle-runtime` checks both bundled CLI entrypoints without access to the source checkout.
- `local-notify` keeps cloud and default synthetic workers silent.

## How to get to it (user POV)

- Use `./run sync` and `./run prepare` with a selected account and vehicle.
- Use `./run cloud status`, `./run cloud pull` or `./run cloud map`.
- Configure private collection with `./run cloud install`.

## Driving it with unittest

Preconditions:

- Python dependencies are available.
- Use the existing synthetic adapters and temporary directories in the tests.

Run `npm run verify -- --suite python`. `tests/test_cloud.py` checks authenticated state, due gating, archive merge, image scope and disabled status. `tests/test_schedule.py` checks retry clocks, process locks and notification transitions. `tests/test_public_map.py` checks the receiver, static host, allowlist and standalone bundle imports. `tests/test_stops.py` checks incomplete chronology and exact derived seconds. `tests/test_public_updates.py` and `tests/test_public_update_worker.py` cover cooldown, dispatch and success validation with synthetic upstream responses. The notifier is intercepted by these suites. Require test exit code zero and inspect any failure log.

When the user's task separately authorizes live cloud acceptance, use the real status/download commands and check the actual encrypted archive, image and local dataset. Report that proof separately from unit tests.

## Gotchas

- `./run cloud run` forces real acquisition; default verification does not call it.
- `cloud install` changes Secrets and deploys a private source snapshot.
- Successful synthetic tests do not establish current credentials or target repository permissions.
- Archive, public image, website publication and local download have separate success states. A publish-only workflow validates publication without proving new acquisition.
