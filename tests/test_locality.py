import os

from api_reality_check.locality import is_local_module, project_root, pythonpath_has_module


def _project(tmp_path):
    root = tmp_path / "proj"
    (root / "app" / "sub").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    f = root / "app" / "sub" / "main.py"
    f.write_text("")
    return root, f


def test_sibling_package_dir_is_local(tmp_path):
    root, f = _project(tmp_path)
    (f.parent / "localpkg").mkdir()
    assert is_local_module("localpkg", str(f))


def test_module_file_in_ancestor_up_to_root_is_local(tmp_path):
    root, f = _project(tmp_path)
    (root / "helpers.py").write_text("")
    assert is_local_module("helpers", str(f))


def test_src_layout_is_local(tmp_path):
    root, f = _project(tmp_path)
    (root / "src" / "mylib").mkdir(parents=True)
    assert is_local_module("mylib", str(f))


def test_unrelated_name_is_not_local(tmp_path):
    root, f = _project(tmp_path)
    assert not is_local_module("numpy", str(f))


def test_project_root_found(tmp_path):
    root, f = _project(tmp_path)
    assert project_root(str(f)) == str(root)


def test_pythonpath_entry_containing_module(tmp_path):
    d = tmp_path / "pp"
    d.mkdir()
    (d / "ppmod.py").write_text("")
    assert pythonpath_has_module("ppmod", [str(d)])
    assert not pythonpath_has_module("other", [str(d)])


def test_walk_without_project_root_never_reaches_filesystem_root(tmp_path):
    # F5: /sys was taken for a local module named sys when the walk reached /.
    f = tmp_path / "a" / "b" / "main.py"
    f.parent.mkdir(parents=True)
    f.write_text("")
    assert os.path.isdir("/sys") or os.path.isdir("/usr")
    assert not is_local_module("sys", str(f)) and not is_local_module("usr", str(f))


def test_walk_without_project_root_stops_at_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    f = home / "x" / "y" / "main.py"
    f.parent.mkdir(parents=True)
    f.write_text("")
    (tmp_path / "above_home_mod.py").write_text("")
    (home / "in_home_mod.py").write_text("")
    monkeypatch.setenv("HOME", str(home))
    assert is_local_module("in_home_mod", str(f))
    assert not is_local_module("above_home_mod", str(f))


def test_stdlib_name_in_a_system_ancestor_dir_is_not_local(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    f = tmp_path / "a" / "b" / "main.py"
    f.parent.mkdir(parents=True)
    f.write_text("")
    (tmp_path / "a" / "json").mkdir()
    (tmp_path / "a" / "helpers.py").write_text("")
    assert not is_local_module("json", str(f))
    assert is_local_module("helpers", str(f))


def test_stdlib_name_beside_the_file_is_still_local(tmp_path):
    f = tmp_path / "a" / "main.py"
    f.parent.mkdir(parents=True)
    f.write_text("")
    (f.parent / "json.py").write_text("")
    assert is_local_module("json", str(f))


def test_locality_lists_each_directory_once(tmp_path, monkeypatch):
    from api_reality_check import locality
    root, f = _project(tmp_path)
    calls = []
    real = os.listdir
    monkeypatch.setattr(locality.os, "listdir", lambda d: calls.append(d) or real(d))
    loc = locality.Locality()
    for i in range(50):
        loc.is_local_module(f"name{i}", str(f))
    assert len(calls) == len(set(calls)), calls
