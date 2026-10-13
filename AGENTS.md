# Project navigation

- Project documentation starts at [docs/README.md](docs/README.md).
- Verify CLI and map changes with [.agents/skills/verify-ninebot-map/SKILL.md](.agents/skills/verify-ninebot-map/SKILL.md).
- Read [docs/design/README.md](docs/design/README.md) before using Impeccable on this map.
- Read [docs/operations.md](docs/operations.md) before changing collection, cloud deployment, or public publishing.
- Keep reusable project skills in `.agents/skills/` and project documentation in `docs/`.

# Main-view copy

- Show user content in the main map view. Keep activity names, durations, update times and badminton counts compact.
- Keep internal implementation and data-quality or verification status in developer documentation and acceptance evidence. Do not add persistent main-view copy such as `推算`, `坐标未核验` or `待验证`, substitute equivalent wording, or reserve space with question-mark badges or empty explanation rows. The main-view nature-duration title and accessible label use the activity name and value.
- Preserve useful error feedback and permission prompts that help users act. Keep the collapsed statistics explanation available. Report technical limits and discovered problems accurately in documentation and verification reports.

# Cursor Cloud specific instructions

- The image has Node and Python 3.12. Install uv 0.13.0 with `UV_NO_MODIFY_PATH=1` and link `uv` and `uvx` into `/usr/local/bin`, then run `./scripts/setup.sh` and `npm ci`. Python 3.12 satisfies `requires-python`.
- Google Chrome is `/opt/google/chrome/chrome`. `npm run verify:doctor` and `npm run verify:smoke` use that Chrome. Set `PLAYWRIGHT_CHANNEL=chromium` only after `npx playwright install chromium` when Chrome is missing.
- The map is on demand and does not start on boot. `./run map --dataset examples/ride-dataset.json --port 8765 --no-open` serves the synthetic example at `http://127.0.0.1:8765/` with no account.
- `./run doctor`, `./run validate examples/ride-dataset.json`, and `.venv/bin/python -m unittest discover -s tests -q` check the local CLI without Ninebot or GitHub credentials.
