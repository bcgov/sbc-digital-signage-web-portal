import os
import json
import zipfile

import pytest

from updater.updater import PACKAGE_LAYOUT_VERSION, UpdateError, Updater, sha256_file


def write_text(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def make_fake_sudo(bin_dir):
    sudo_path = bin_dir / "sudo"
    write_text(sudo_path, "#!/bin/sh\nexec \"$@\"\n", executable=True)
    return sudo_path


def make_update_stage(root, predeploy_scripts=None, postdeploy_scripts=None):
    predeploy_scripts = predeploy_scripts or {}
    postdeploy_scripts = postdeploy_scripts or {}

    write_text(root / "main.py", "print('main')\n")
    write_text(root / "app" / "main.py", "from app import APP\nprint(APP)\n")
    write_text(root / "app" / "app" / "__init__.py", "APP = 'ok'\n")
    write_text(root / "updater" / "updater.py", "print('updater')\n")
    write_text(root / "tools" / "helper.py", "print('tool')\n")
    write_text(root / "scripts" / "provision.sh", "#!/bin/sh\nexit 0\n", executable=True)
    write_text(root / "deploy" / "sudoers" / "video-portal-update", "pi ALL=(ALL) NOPASSWD: ALL\n")
    write_text(root / ".python-version", "3.14.4\n")
    write_text(root / "pyproject.toml", "[project]\nname='demo'\nversion='0.0.0'\n")
    write_text(root / "uv.lock", "version = 1\n")
    write_text(root / "VERSION", "1.2.3\n")
    write_text(root / "uv-cache" / "cache.db", "cached\n")

    if predeploy_scripts:
        for name, body in predeploy_scripts.items():
            write_text(root / "scripts" / "predeploy" / name, body, executable=True)
    else:
        write_text(root / "scripts" / "predeploy" / ".gitkeep", "")

    if postdeploy_scripts:
        for name, body in postdeploy_scripts.items():
            write_text(root / "scripts" / "postdeploy" / name, body, executable=True)
    else:
        write_text(root / "scripts" / "postdeploy" / ".gitkeep", "")

    manifest = {
        "package_layout_version": PACKAGE_LAYOUT_VERSION,
        "version": "1.2.3",
        "python": "3.14.4",
        "entrypoint": "app/main.py",
        "project_root": ".",
        "uv_cache": "uv-cache",
        "healthcheck_url": "http://127.0.0.1/healthz",
        "supervisor_programs": ["video_looper"],
        "files": {},
    }

    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            manifest["files"][path.relative_to(root).as_posix()] = sha256_file(path)

    write_text(
        root / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return root


def zip_tree(source_root, destination):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(source_root).as_posix())


def make_updater(monkeypatch, portal_root):
    monkeypatch.setenv("VIDEO_PORTAL_UV_BIN", "/bin/sh")
    monkeypatch.setenv("VIDEO_PORTAL_USE_SUDO", "false")
    updater = Updater(portal_root=portal_root)
    updater.install_dependencies = lambda release_dir, manifest: None
    updater.restart_supervisor_programs = lambda manifest: None
    updater.wait_for_healthcheck = lambda url, version: {"status": "ok", "version": version}
    return updater


def seed_current_release(portal_root, release_name="baseline"):
    release_dir = portal_root / "releases" / release_name
    write_text(release_dir / "app" / "main.py", "print('baseline')\n")
    write_text(
        release_dir / "manifest.json",
        json.dumps({"healthcheck_url": "http://127.0.0.1/healthz"}) + "\n",
    )
    write_text(release_dir / "VERSION", "0.9.0\n")
    current_path = portal_root / "current"
    current_path.parent.mkdir(parents=True, exist_ok=True)
    if current_path.exists() or current_path.is_symlink():
        current_path.unlink()
    current_path.symlink_to(release_dir)
    return release_dir


def test_load_manifest_requires_full_project_directories(tmp_path, monkeypatch):
    updater = make_updater(monkeypatch, tmp_path / "portal")
    updater.ensure_layout()

    stage_root = tmp_path / "stage"
    make_update_stage(stage_root)
    updater_dir = stage_root / "updater"
    for child in updater_dir.iterdir():
        child.unlink()
    updater_dir.rmdir()

    with pytest.raises(UpdateError, match="missing updater/ contents"):
        updater.load_manifest(stage_root)


def test_run_migration_phase_only_runs_newer_scripts(tmp_path, monkeypatch):
    updater = make_updater(monkeypatch, tmp_path / "portal")
    release_dir = tmp_path / "release"
    write_text(release_dir / "scripts" / "predeploy" / "0001_first.sh", "#!/bin/sh\n")
    write_text(release_dir / "scripts" / "predeploy" / "0002_second.sh", "#!/bin/sh\n")

    calls = []
    updater.run_migration_script = (
        lambda phase, version, script_path, release_dir, manifest, previous_release: calls.append((phase, version, script_path.name))
    )
    state = {"last_successful_predeploy_migration": "0001"}

    updater.run_migration_phase(
        "predeploy",
        release_dir,
        {"version": "1.2.3"},
        "baseline",
        state,
    )

    assert calls == [("predeploy", "0002", "0002_second.sh")]
    assert state["last_successful_predeploy_migration"] == "0002"


def test_process_package_runs_migrations_and_supports_sudo_in_hooks(
    tmp_path, monkeypatch
):
    portal_root = tmp_path / "portal"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_sudo(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    updater = make_updater(monkeypatch, portal_root)
    updater.ensure_layout()

    stage_root = tmp_path / "stage"
    make_update_stage(
        stage_root,
        predeploy_scripts={
            "0001_pre.sh": (
                "#!/bin/sh\n"
                "sudo sh -c 'printf pre > \"$1\"' sh \"$VIDEO_PORTAL_PORTAL_ROOT/pre.txt\"\n"
            )
        },
        postdeploy_scripts={
            "0002_post.sh": (
                "#!/bin/sh\n"
                "printf post > \"$VIDEO_PORTAL_PORTAL_ROOT/post.txt\"\n"
            )
        },
    )
    package_path = tmp_path / "release.zip"
    zip_tree(stage_root, package_path)

    updater.process_package(package_path, updater.load_state(), "attempt-1")
    state = updater.load_state()

    assert (portal_root / "pre.txt").read_text(encoding="utf-8") == "pre"
    assert (portal_root / "post.txt").read_text(encoding="utf-8") == "post"
    assert state["last_successful_predeploy_migration"] == "0001"
    assert state["last_successful_postdeploy_migration"] == "0002"
    assert state["last_known_good"] == state["active_release"]
    assert (portal_root / "current" / "updater" / "updater.py").exists()
    assert (portal_root / "current" / "tools" / "helper.py").exists()


def test_postdeploy_failure_rolls_back_to_previous_release(tmp_path, monkeypatch):
    portal_root = tmp_path / "portal"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_fake_sudo(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    updater = make_updater(monkeypatch, portal_root)
    updater.ensure_layout()

    seed_current_release(portal_root)
    state = updater.load_state()
    state["active_release"] = "baseline"
    state["last_known_good"] = "baseline"
    updater.save_state(state)

    stage_root = tmp_path / "stage"
    make_update_stage(
        stage_root,
        predeploy_scripts={
            "0001_pre.sh": "#!/bin/sh\nprintf ok > \"$VIDEO_PORTAL_PORTAL_ROOT/pre.txt\"\n"
        },
        postdeploy_scripts={"0002_post.sh": "#!/bin/sh\nexit 1\n"},
    )
    package_path = tmp_path / "release.zip"
    zip_tree(stage_root, package_path)

    with pytest.raises(UpdateError, match="postdeploy migration failed"):
        updater.process_package(package_path, updater.load_state(), "attempt-2")

    state = updater.load_state()
    assert portal_root.joinpath("current").resolve().name == "baseline"
    assert state["active_release"] == "baseline"
    assert state["last_known_good"] == "baseline"
    assert state["last_successful_predeploy_migration"] == "0001"
    assert state["last_successful_postdeploy_migration"] is None
    assert any(portal_root.joinpath("releases_failed").iterdir())
