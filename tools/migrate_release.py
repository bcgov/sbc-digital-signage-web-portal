#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from updater.updater import (  # noqa: E402
    ensure_shared_dir,
    migrate_legacy_root_env_file,
    overlay_shared_tree,
)

RELEASE_ROOT_DIRS = (
    "updater",
    "tools",
    "scripts",
    "deploy",
)
PROJECT_METADATA_ENTRIES = (
    ".python-version",
    "pyproject.toml",
    "uv.lock",
)
ROOT_SYMLINKS = ("tools", "scripts", "deploy")

DEFAULT_STATE = {
    "active_release": "initial",
    "last_attempt": None,
    "last_error": None,
    "last_known_good": "initial",
    "last_successful_postdeploy_migration": None,
    "last_successful_predeploy_migration": None,
    "previous_release": None,
    "update_in_progress": False,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Migrate a flat deployment into the release-based layout."
    )
    parser.add_argument("--portal-root", default="/home/pi/video-portal", type=Path)
    parser.add_argument("--release-name", default="initial")
    return parser.parse_args()


def ignore_managed_copy(source_dir, names):
    ignored = {"__pycache__", ".DS_Store"}
    if Path(source_dir).name == "updater":
        ignored.add("state.json")
    return ignored.intersection(names)


def create_symlink(link_path, target_path):
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_dir() and not link_path.is_symlink():
            shutil.rmtree(link_path)
        else:
            link_path.unlink()

    relative_target = os.path.relpath(target_path, start=link_path.parent)
    link_path.symlink_to(relative_target)


def move_existing_app(portal_root, release_name):
    releases_dir = portal_root / "releases"
    release_dir = releases_dir / release_name
    release_app_root = release_dir / "app"
    app_package_root = release_app_root / "app"

    if release_dir.exists():
        raise RuntimeError("Target release already exists: %s" % release_dir)

    release_dir.mkdir(parents=True, exist_ok=False)
    release_app_root.mkdir(parents=True, exist_ok=False)
    app_package_root.parent.mkdir(parents=True, exist_ok=True)

    main_py = portal_root / "main.py"
    if not main_py.exists():
        raise RuntimeError("Missing main.py in %s" % portal_root)
    shutil.copy2(main_py, release_dir / "main.py")
    shutil.move(str(main_py), str(release_app_root / "main.py"))

    app_package_source = portal_root / "app"
    if not app_package_source.exists():
        raise RuntimeError("Missing app package in %s" % portal_root)
    shutil.move(str(app_package_source), str(app_package_root))

    for relative_name in RELEASE_ROOT_DIRS:
        source = portal_root / relative_name
        if not source.exists():
            raise RuntimeError("Missing runtime directory: %s" % source)
        if relative_name == "updater":
            shutil.copytree(source, release_dir / relative_name, ignore=ignore_managed_copy)
            shutil.rmtree(source)
        else:
            shutil.move(str(source), str(release_dir / relative_name))

    for relative_name in PROJECT_METADATA_ENTRIES:
        source = portal_root / relative_name
        if not source.exists():
            raise RuntimeError("Missing project metadata file: %s" % source)
        shutil.move(str(source), str(release_dir / relative_name))

    version_path = portal_root / "VERSION"
    if version_path.exists():
        shutil.copy2(version_path, release_dir / "VERSION")
        version_path.unlink()

    current_path = portal_root / "current"
    if current_path.exists() or current_path.is_symlink():
        if not current_path.is_symlink():
            raise RuntimeError(
                "Existing current path is not a symlink: %s" % current_path
            )
        current_path.unlink()
    current_path.symlink_to(release_dir)

    for relative_name in ROOT_SYMLINKS:
        create_symlink(portal_root / relative_name, current_path / relative_name)

    return release_dir


def write_state(portal_root, release_name):
    updater_dir = portal_root / "updater"
    updater_dir.mkdir(parents=True, exist_ok=True)
    state_path = updater_dir / "state.json"
    state = dict(DEFAULT_STATE)
    state["active_release"] = release_name
    state["last_known_good"] = release_name
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def ensure_runtime_dirs(portal_root):
    for path in (
        portal_root / "releases",
        portal_root / "releases_failed",
        portal_root / "shared",
        portal_root / "updates" / "incoming",
        portal_root / "updates" / "staging",
        portal_root / "updates" / "logs",
        portal_root / "updater",
        portal_root / "logs",
    ):
        path.mkdir(parents=True, exist_ok=True)


def main():
    args = parse_args()
    portal_root = args.portal_root.expanduser().resolve()

    current_path = portal_root / "current"
    if current_path.is_symlink():
        print("Release layout already present at %s" % portal_root)
        return

    ensure_runtime_dirs(portal_root)
    shared_root = ensure_shared_dir(portal_root)
    migrate_legacy_root_env_file(portal_root, shared_root)
    release_dir = move_existing_app(portal_root, args.release_name)
    overlay_shared_tree(shared_root, release_dir)
    write_state(portal_root, args.release_name)
    print("Migrated application into %s" % release_dir)
    print("Current symlink now points to %s" % release_dir)


if __name__ == "__main__":
    main()
