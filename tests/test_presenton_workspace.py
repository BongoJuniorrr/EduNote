"""The separate slide service cannot read/write outside its own data and temp roots."""
import importlib.util
from pathlib import Path
import pytest
from fastapi import HTTPException

spec=importlib.util.spec_from_file_location('presenton_safe_paths',Path(__file__).parents[1]/'presenton/servers/fastapi/utils/safe_paths.py')
paths=importlib.util.module_from_spec(spec);spec.loader.exec_module(paths)


def test_presenton_files_stay_within_data_or_temp(tmp_path,monkeypatch):
    data=tmp_path/'data';temp=tmp_path/'temp';data.mkdir();temp.mkdir()
    monkeypatch.setenv('APP_DATA_DIRECTORY',str(data));monkeypatch.setenv('TEMP_DIRECTORY',str(temp))
    assert paths.workspace_file(str(data/'images'/'test.png')) == str(data/'images'/'test.png')
    assert paths.workspace_file(str(temp/'document.txt')) == str(temp/'document.txt')
    for filename in ['/etc/passwd',str(data/'..'/'outside.txt'),str(tmp_path/'data-other'/'file.txt')]:
        with pytest.raises(HTTPException):paths.workspace_file(filename)
    outside=tmp_path/'outside';outside.mkdir();(data/'link').symlink_to(outside,target_is_directory=True)
    with pytest.raises(HTTPException):paths.workspace_file(str(data/'link'/'file.txt'))


def test_presenton_resource_names_reject_separators():
    for name in ['../font.ttf','a/b.ttf','a\\b.ttf','..','']:
        with pytest.raises(HTTPException):paths.leaf_name(name)
    assert paths.leaf_name('VGU-font.ttf') == 'VGU-font.ttf'
