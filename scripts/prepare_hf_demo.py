"""Build one ZeroGPU Space containing the React UI and OCR API."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / 'deploy' / 'huggingface'


def prepare_backend(destination: Path) -> None:
    destination.mkdir(parents=True)
    # Only source packages are exported. Never copy .env, uploads, model caches,
    # outputs, credentials, or version-control metadata into a public Space.
    for package in ('config', 'core', 'services'):
        for source in (REPO_ROOT / package).rglob('*.py'):
            target = destination / source.relative_to(REPO_ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for name in ('app.py', 'requirements.txt', 'packages.txt'):
        shutil.copy2(TEMPLATES / name, destination / name)
    runtime_target = destination / 'deploy' / 'huggingface' / 'runtime.py'
    runtime_target.parent.mkdir(parents=True)
    shutil.copy2(TEMPLATES / 'runtime.py', runtime_target)
    shutil.copy2(TEMPLATES / 'backend-readme.md', destination / 'README.md')
    shutil.copy2(REPO_ROOT / 'LICENSE', destination / 'LICENSE')


def prepare(backend_space: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', backend_space):
        raise ValueError('--backend-space must have the form username/space-name')
    scratch = REPO_ROOT / 'test'
    scratch.mkdir(exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='hf-demo-', dir=scratch))
    prepare_backend(destination / 'space')
    environment = dict(os.environ, VITE_GRADIO_SPACE='self')
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise RuntimeError('Node.js and npm are required to build the React frontend.')
    subprocess.run([npm, 'run', 'build'], cwd=REPO_ROOT / 'frontend',
                   env=environment, check=True)
    shutil.copytree(REPO_ROOT / 'frontend' / 'dist', destination / 'space' / 'frontend' / 'dist')
    (destination / 'backend-space.txt').write_text(backend_space, encoding='utf-8')
    print(f'Prepared demo: {destination}')
    print(f'Demo: https://huggingface.co/spaces/{backend_space}')
    return destination


if __name__ == '__main__':
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument('--backend-space', required=True)
    arguments = argument_parser.parse_args()
    prepare(arguments.backend_space)
