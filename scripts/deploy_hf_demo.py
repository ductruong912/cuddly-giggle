"""Publish one public React OCR demo Space using only free ZeroGPU hardware."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.prepare_hf_demo import prepare


def deploy(name: str = 'cuddly-giggle-demo') -> None:
    from huggingface_hub import HfApi, SpaceHardware, get_token
    from huggingface_hub.errors import HfHubHTTPError

    if not get_token():
        raise SystemExit('Sign in with venv/Scripts/hf.exe auth login first. Never paste a token into chat.')
    api = HfApi()
    username = api.whoami()['name']
    space_id = f'{username}/{name}'
    if api.repo_exists(space_id, repo_type='space'):
        raise SystemExit(f'{space_id} already exists; choose another --name. No existing Space was changed.')

    package = prepare(space_id)
    try:
        api.create_repo(repo_id=space_id, repo_type='space', private=False,
                        space_sdk='gradio', space_hardware=SpaceHardware.ZERO_A10G)
    except HfHubHTTPError as exc:
        if exc.response is not None and exc.response.status_code == 402:
            raise SystemExit(
                f'Hugging Face has not enabled free ZeroGPU hosting for {username} '
                '(HTTP 402). Check verified email, account age over 30 days, and '
                'free ZeroGPU availability. Stopped without requesting paid hardware '
                'or uploading code. The prepared package is at ' + str(package)
            ) from None
        raise
    runtime = api.get_space_runtime(space_id)
    requested = runtime.requested_hardware or runtime.hardware
    if requested != SpaceHardware.ZERO_A10G:
        raise SystemExit(f'Expected free ZeroGPU, got {requested!r}. Stopped before uploading code.')
    api.upload_folder(repo_id=space_id, repo_type='space', folder_path=package / 'space',
                      commit_message='Deploy React OCR playground with free ZeroGPU')
    deployment = dict(space=space_id, hardware='zero-a10g')
    (package / 'deployment.json').write_text(json.dumps(deployment, indent=2), encoding='utf-8')
    print(f'Demo: https://huggingface.co/spaces/{space_id}')
    print('Uploaded. Check build logs and perform an OCR request before calling the demo verified.')


if __name__ == '__main__':
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument('--name', default='cuddly-giggle-demo')
    arguments = argument_parser.parse_args()
    deploy(arguments.name)
