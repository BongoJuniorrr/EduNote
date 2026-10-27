"""File access stays inside Presenton's data/temp/static directories."""
import os
from pathlib import Path
from fastapi import HTTPException


def workspace_file(value: str, *, allow_static: bool = False) -> str:
    candidate = os.path.abspath(value)
    roots = [os.path.realpath(os.getenv('APP_DATA_DIRECTORY', '/app_data')), os.path.realpath(os.getenv('TEMP_DIRECTORY', '/tmp/presenton'))]
    if allow_static:
        roots.append(os.path.realpath(Path(__file__).resolve().parents[1] / 'static'))
    for root in roots:
        if candidate.startswith(root + os.sep):
            resolved = os.path.realpath(candidate)
            if resolved.startswith(root + os.sep):
                return resolved
    raise HTTPException(status_code=400, detail='File is outside the presentation workspace')


def leaf_name(value: str) -> str:
    if not value or value in {'.','..'} or any(c in value for c in ('/', '\\', '\x00')):
        raise HTTPException(status_code=400, detail='Invalid filename')
    return os.path.basename(value)
