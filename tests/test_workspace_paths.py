from pathlib import Path
import pytest
from src.security.paths import InvalidPathError, safe_child, safe_leaf
from src.security.svg import sanitize_svg

@pytest.mark.parametrize('name', ['../outside','..','.','/etc/passwd','a/b','a\\b','', 'bad\x00id'])
def test_resource_ids_cannot_escape_workspace(tmp_path,name):
    with pytest.raises(InvalidPathError):safe_child(tmp_path,name)


def test_resource_names_are_preserved_and_symlinks_cannot_escape(tmp_path):
    assert safe_leaf('Tài liệu CSE.1') == 'Tài liệu CSE.1'
    assert safe_child(tmp_path,'resource.json') == tmp_path/'resource.json'
    outside = tmp_path.parent/'outside-test';outside.mkdir(exist_ok=True)
    (tmp_path/'linked').symlink_to(outside,target_is_directory=True)
    with pytest.raises(InvalidPathError):safe_child(tmp_path,'linked','secret.json')


def test_generated_svg_removes_active_content_and_external_references():
    clean=sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg" onload="evil()"><script>evil()</script><foreignObject><div>html</div></foreignObject><use href="https://example.org/a.svg"/><path d="M0 0" fill="red"/></svg>')
    assert 'script' not in clean and 'onload' not in clean and 'foreignObject' not in clean
    assert 'https://' not in clean and 'M0 0' in clean


def test_generated_svg_rejects_entity_expansion():
    with pytest.raises(Exception):sanitize_svg('<!DOCTYPE svg [<!ENTITY a "expanded">]><svg>&a;</svg>')
