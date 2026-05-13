#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path


PACKAGE_LAYOUT_VERSION = 2
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
UV_CACHE_DIR_NAME = "uv-cache"
SUPERVISOR_PROGRAMS = ["video_looper"]


class BuildUpdateZipError(Exception):
    """Raised when the update package cannot be built."""


def sha256_file(path):
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_version(source_root, override=None, fallback="0.0.0"):
    if override:
        return override
    version_path = source_root / "VERSION"
    if version_path.exists():
        version_text = version_path.read_text(encoding="utf-8").strip()
        if version_text:
            return version_text
    return fallback


def read_python_version(source_root):
    version_path = Path(source_root) / ".python-version"
    if not version_path.exists():
        raise BuildUpdateZipError("Source tree is missing .python-version.")

    python_version = version_path.read_text(encoding="utf-8").strip()
    if not python_version:
        raise BuildUpdateZipError("Source tree .python-version cannot be empty.")
    return python_version


def resolve_source_root(source_root):
    source_root = Path(source_root).resolve()
    candidates = (
        source_root,
        source_root / "current",
    )

    for candidate in candidates:
        if all(
            (candidate / relative_name).exists()
            for relative_name in ("app", "main.py", *RELEASE_ROOT_DIRS, *PROJECT_METADATA_ENTRIES)
        ):
            return candidate.resolve()

    raise FileNotFoundError("Could not find runtime files under %s" % source_root)


def ignore_managed_copy(source_dir, names):
    ignored = {"__pycache__", ".DS_Store"}
    if Path(source_dir).name == "updater":
        ignored.add("state.json")
    return ignored.intersection(names)


def copy_release_tree(source_root, stage_root):
    source_root = Path(source_root)
    stage_root = Path(stage_root)

    app_runtime_root = stage_root / "app"
    app_runtime_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "main.py", stage_root / "main.py")
    shutil.copy2(source_root / "main.py", app_runtime_root / "main.py")
    shutil.copytree(
        source_root / "app",
        app_runtime_root / "app",
        ignore=ignore_managed_copy,
    )

    for relative_name in RELEASE_ROOT_DIRS:
        shutil.copytree(
            source_root / relative_name,
            stage_root / relative_name,
            ignore=ignore_managed_copy,
        )

    copy_project_metadata(source_root, stage_root)


def copy_project_metadata(project_source, project_destination):
    project_destination.mkdir(parents=True, exist_ok=True)
    for relative_name in PROJECT_METADATA_ENTRIES:
        shutil.copy2(
            project_source / relative_name,
            project_destination / relative_name,
        )


def warm_uv_cache(uv_executable, project_source, build_dir, python_version, cache_dir):
    project_root = build_dir / "uv-project"
    python_install_dir = build_dir / "uv-python"
    uv_env = os.environ.copy()
    uv_env.update(
        {
        "UV_PYTHON_INSTALL_DIR": str(python_install_dir),
        }
    )
    if project_root.exists():
        shutil.rmtree(project_root)

    copy_project_metadata(project_source, project_root)
    subprocess.run(
        [str(uv_executable), "python", "install", python_version],
        check=True,
        env=uv_env,
    )
    subprocess.run(
        [
            str(uv_executable),
            "sync",
            "--project",
            str(project_root),
            "--python",
            python_version,
            "--frozen",
            "--no-dev",
            "--no-install-project",
            "--cache-dir",
            str(cache_dir),
        ],
        check=True,
        env=uv_env,
    )


def generate_manifest(stage_root, version, python_version, healthcheck_url):
    file_hashes = {}
    for path in sorted(stage_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(stage_root).as_posix()
        if relative_path == "manifest.json":
            continue
        file_hashes[relative_path] = sha256_file(path)

    manifest = {
        "package_layout_version": PACKAGE_LAYOUT_VERSION,
        "version": version,
        "python": python_version,
        "entrypoint": "app/main.py",
        "project_root": ".",
        "uv_cache": UV_CACHE_DIR_NAME,
        "healthcheck_url": healthcheck_url,
        "supervisor_programs": SUPERVISOR_PROGRAMS,
        "files": file_hashes,
    }
    manifest_path = stage_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def build_archive(stage_root, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(stage_root).as_posix())


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build an offline update package for the Video Portal."
    )
    parser.add_argument(
        "--source-root", default=Path(__file__).resolve().parent.parent, type=Path
    )
    parser.add_argument("--output-dir", default=Path("dist"), type=Path)
    parser.add_argument("--build-dir", default=Path("build/update-package"), type=Path)
    parser.add_argument("--uv-executable", default="uv")
    parser.add_argument("--healthcheck-url", default="http://127.0.0.1:80/healthz")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(argv)
        build_dir = args.build_dir.resolve()
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)

        source_root = resolve_source_root(args.source_root)
        python_version = read_python_version(source_root)
        version = read_version(source_root)

        stage_root = build_dir / "stage"
        uv_cache_dir = stage_root / UV_CACHE_DIR_NAME
        stage_root.mkdir(parents=True, exist_ok=True)
        uv_cache_dir.mkdir(parents=True, exist_ok=True)

        copy_release_tree(source_root, stage_root)
        warm_uv_cache(
            args.uv_executable,
            stage_root,
            build_dir,
            python_version,
            uv_cache_dir,
        )

        version_path = stage_root / "VERSION"
        version_path.write_text(version + "\n", encoding="utf-8")
        generate_manifest(stage_root, version, python_version, args.healthcheck_url)

        archive_name = "video-portal-update-%s.zip" % version
        output_path = args.output_dir.resolve() / archive_name
        build_archive(stage_root, output_path)
        print(output_path)
    except BuildUpdateZipError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
