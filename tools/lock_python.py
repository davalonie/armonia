"""Run in the reviewed development venv to record the resolved production graph."""
from importlib import metadata
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

root = Path(__file__).resolve().parents[1] / 'middleware'
requested = [Requirement(line) for line in (root / 'requirements.txt').read_text().splitlines()
             if line and not line.startswith('#')]
seen, pending = {}, list(requested)
while pending:
    req = pending.pop()
    name = canonicalize_name(req.name)
    extras = set(req.extras) | {''}
    previous = seen.get(name, set())
    if name in seen and extras <= previous:
        continue
    seen[name] = previous | extras
    for raw in metadata.requires(name) or []:
        dependency = Requirement(raw)
        if not dependency.marker or any(dependency.marker.evaluate({'extra': e}) for e in extras):
            pending.append(dependency)
(root / 'requirements.lock').write_text('# Resolved 2026-11-10, Python 3.12 Linux; regenerate deliberately.\n' +
    '\n'.join(f'{name}=={metadata.version(name)}' for name in sorted(seen)) + '\n')
