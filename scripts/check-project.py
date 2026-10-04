#!/usr/bin/env python3
"""Check project-owned documentation, skills, and publication boundaries."""
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.git', 'AGENTS.md', 'README.md', 'LICENSE', 'run', 'start.command',
              'package.json', 'package-lock.json', 'pyproject.toml', 'uv.lock', '.gitignore', '.DS_Store'}
ROOT_DIRS = {'.git', '.github', '.agents', '.venv', '.private', 'assets', 'data', 'docs', 'examples',
             'nbmap', 'node_modules', 'schemas', 'scripts', 'templates', 'tests', 'web', 'work', 'outputs'}
DEPLOYMENT_FILES = {'sync-settings.json', 'github-known-hosts'}
deployment = all((ROOT / name).is_file() for name in DEPLOYMENT_FILES)
FEATURE_HEADINGS = ['Sub-features', 'How to get to it (user POV)', 'Driving it with ', 'Gotchas']
errors = []

for entry in ROOT.iterdir():
    allowed = ROOT_DIRS if entry.is_dir() else ROOT_FILES | (DEPLOYMENT_FILES if deployment else set())
    if entry.name not in allowed:
        errors.append(f'Root entry is outside the project layout: {entry.name}')

skills = sorted((ROOT / '.agents/skills').glob('*/SKILL.md'))
if not skills:
    errors.append('No project-local skills found')
for path in skills:
    text = path.read_text()
    frontmatter = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    if not frontmatter:
        errors.append(f'{path.relative_to(ROOT)} has no frontmatter')
        continue
    name = re.search(r'^name: (.+)$', frontmatter[1], re.M)
    description = re.search(r'^description: (.+)$', frontmatter[1], re.M)
    if not name or name[1] != path.parent.name or not description:
        errors.append(f'{path.relative_to(ROOT)} has inconsistent name or missing description')
    for feature in (path.parent / 'features').glob('*.md'):
        if feature.name == 'README.md':
            continue
        headings = re.findall(r'^## (.+)$', feature.read_text(), re.M)
        if (len(headings) != 4 or headings[:2] != FEATURE_HEADINGS[:2]
                or not headings[2].startswith(FEATURE_HEADINGS[2]) or headings[3] != FEATURE_HEADINGS[3]):
            errors.append(f'{feature.relative_to(ROOT)} has an invalid feature recipe')

markdown = [ROOT / 'README.md', ROOT / 'AGENTS.md']
markdown.extend((ROOT / 'docs').rglob('*.md'))
markdown.extend((ROOT / '.agents').rglob('*.md'))
for path in markdown:
    text = path.read_text()
    for target in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)', text):
        if re.match(r'^[a-z][a-z0-9+.-]*:', target, re.I) or target.startswith('#'):
            continue
        target = unquote(target.strip('<>').split('#', 1)[0])
        if target and not (path.parent / target).exists():
            errors.append(f'{path.relative_to(ROOT)} links to missing {target}')

tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, text=True)
if tracked.returncode == 0:
    for relative in tracked.stdout.split('\0'):
        if not relative:
            continue
        path = Path(relative)
        if set(path.parts) & {'.private', 'data', 'work', 'outputs', '.venv', 'node_modules', '__pycache__'}:
            errors.append(f'Tracked runtime file: {relative}')
        if path.suffix in {'.key', '.pem', '.csv', '.gpx', '.fit', '.tcx', '.har', '.db', '.pyc'}:
            errors.append(f'Tracked private-data format: {relative}')
        actual = ROOT / path
        if actual.is_file() and actual.suffix in {'.md', '.py', '.mjs', '.js', '.json', '.yml', '.yaml'}:
            if re.search(rb'(?m)^-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----', actual.read_bytes()):
                errors.append(f'Private key content: {relative}')

for name in ('verify.mjs', 'check-project.py'):
    path = ROOT / 'scripts' / name
    if not path.is_file() or not path.stat().st_mode & 0o111:
        errors.append(f'Helper is missing or not executable: scripts/{name}')

print(json.dumps({'passed': not errors, 'layout': 'private-source-snapshot' if deployment else 'public-project', 'project_skills': len(skills),
                  'markdown_files_checked': len(markdown), 'errors': errors}, ensure_ascii=False, indent=2))
sys.exit(bool(errors))
