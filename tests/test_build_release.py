import json

from tools import build_release


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_source_tree(root):
    write_text(root / "main.py", "print('main')\n")
    write_text(root / "app" / "__init__.py", "APP = True\n")
    write_text(root / "updater" / "updater.py", "print('updater')\n")
    write_text(root / "updater" / "state.json", "{}\n")
    write_text(root / "tools" / "helper.py", "print('tool')\n")
    write_text(root / "scripts" / "predeploy" / ".gitkeep", "")
    write_text(root / "scripts" / "postdeploy" / ".gitkeep", "")
    write_text(root / "deploy" / "supervisor" / "portal.conf", "[program:test]\n")
    write_text(root / ".python-version", "3.14.4\n")
    write_text(root / "pyproject.toml", "[project]\nname='demo'\nversion='0.0.0'\n")
    write_text(root / "uv.lock", "version = 1\n")
    write_text(root / "VERSION", "1.2.3\n")


def test_copy_release_tree_and_manifest_cover_full_project_layout(tmp_path):
    source_root = tmp_path / "source"
    stage_root = tmp_path / "stage"
    make_source_tree(source_root)

    build_release.copy_release_tree(source_root, stage_root)
    write_text(stage_root / "uv-cache" / "cache.db", "cached\n")
    write_text(stage_root / "VERSION", "1.2.3\n")

    manifest_path = build_release.generate_manifest(
        stage_root,
        "1.2.3",
        "3.14.4",
        "http://127.0.0.1/healthz",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert (stage_root / "main.py").exists()
    assert (stage_root / "app" / "main.py").exists()
    assert (stage_root / "app" / "app" / "__init__.py").exists()
    assert (stage_root / "updater" / "updater.py").exists()
    assert not (stage_root / "updater" / "state.json").exists()
    assert (stage_root / "tools" / "helper.py").exists()
    assert (stage_root / "scripts" / "predeploy" / ".gitkeep").exists()
    assert (stage_root / "deploy" / "supervisor" / "portal.conf").exists()
    assert (stage_root / ".python-version").exists()

    assert manifest["package_layout_version"] == build_release.PACKAGE_LAYOUT_VERSION
    assert manifest["project_root"] == "."
    assert manifest["entrypoint"] == "app/main.py"
    assert "app_name" not in manifest
    assert manifest["supervisor_programs"] == ["video_looper"]
    assert "main.py" in manifest["files"]
    assert "app/main.py" in manifest["files"]
    assert "app/app/__init__.py" in manifest["files"]
    assert "updater/updater.py" in manifest["files"]
    assert "tools/helper.py" in manifest["files"]
    assert "deploy/supervisor/portal.conf" in manifest["files"]
    assert "VERSION" in manifest["files"]
