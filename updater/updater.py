#!/usr/bin/env python3
import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DEFAULT_STATE = {
    "active_release": None,
    "last_known_good": None,
    "last_successful_postdeploy_migration": None,
    "last_successful_predeploy_migration": None,
    "previous_release": None,
    "update_in_progress": False,
    "last_attempt": None,
    "last_error": None,
}
PACKAGE_LAYOUT_VERSION = 2
PROJECT_LAYOUT_DIRS = (
    "app",
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
MIGRATION_STATE_FIELDS = {
    "predeploy": "last_successful_predeploy_migration",
    "postdeploy": "last_successful_postdeploy_migration",
}
MIGRATION_SCRIPT_PATTERN = re.compile(r"^(?P<version>\d+)_[A-Za-z0-9._-]+\.sh$")


class UpdateError(Exception):
    """Raised when an update cannot be completed safely."""


class HealthCheckError(UpdateError):
    """Raised when the updated application does not become healthy."""


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_shared_dir(portal_root):
    shared_root = Path(portal_root) / "shared"
    shared_root.mkdir(parents=True, exist_ok=True)
    return shared_root


def overlay_shared_tree(shared_root, release_root):
    shared_root = Path(shared_root)
    release_root = Path(release_root)

    if not shared_root.exists():
        return

    for source_path in sorted(shared_root.rglob("*")):
        if not source_path.is_file():
            continue

        relative_path = source_path.relative_to(shared_root)
        destination_path = release_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        if destination_path.exists() or destination_path.is_symlink():
            if destination_path.is_dir() and not destination_path.is_symlink():
                raise RuntimeError(
                    "Shared file conflicts with an existing directory in the release: %s"
                    % destination_path
                )
            destination_path.unlink()

        relative_target = os.path.relpath(source_path, start=destination_path.parent)
        destination_path.symlink_to(relative_target)


def migrate_legacy_root_env_file(portal_root, shared_root):
    portal_root = Path(portal_root)
    shared_root = Path(shared_root)
    legacy_env_path = portal_root / ".env"
    shared_env_path = shared_root / "app" / ".env"

    if not legacy_env_path.exists():
        return

    if shared_env_path.exists():
        raise RuntimeError(
            "Cannot migrate %s because %s already exists."
            % (legacy_env_path, shared_env_path)
        )

    shared_env_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy_env_path), str(shared_env_path))


class Updater:
    def __init__(self, portal_root=None, sleep_func=time.sleep):
        configured_root = (
            portal_root
            or os.environ.get("VIDEO_PORTAL_ROOT")
            or "/home/pi/video-portal"
        )
        self.portal_root = Path(configured_root).expanduser().resolve()
        self.releases_dir = self.portal_root / "releases"
        self.failed_releases_dir = self.portal_root / "releases_failed"
        self.current_path = self.portal_root / "current"
        self.updates_dir = self.portal_root / "updates"
        self.incoming_dir = self.updates_dir / "incoming"
        self.staging_dir = self.updates_dir / "staging"
        self.logs_dir = self.updates_dir / "logs"
        self.updater_dir = self.portal_root / "updater"
        self.shared_dir = self.portal_root / "shared"
        self.state_path = self.updater_dir / "state.json"
        self.lock_path = self.updater_dir / "update.lock"
        self.uv_python_install_dir = os.environ.get(
            "VIDEO_PORTAL_UV_PYTHON_INSTALL_DIR",
            str(self.portal_root / ".uv" / "python"),
        )
        self.app_program_name = os.environ.get(
            "VIDEO_PORTAL_APP_PROGRAM", "video-portal"
        )
        self.use_sudo = os.environ.get("VIDEO_PORTAL_USE_SUDO", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.healthcheck_timeout = int(
            os.environ.get("VIDEO_PORTAL_HEALTHCHECK_TIMEOUT", "60")
        )
        self.healthcheck_interval = float(
            os.environ.get("VIDEO_PORTAL_HEALTHCHECK_INTERVAL", "2")
        )
        self.sleep = sleep_func
        self._log_handle = None
        self.uv_executable = self.resolve_uv_executable()

    def build_subprocess_env(self):
        env = os.environ.copy()
        try:
            user_entry = pwd.getpwuid(os.getuid())
        except KeyError:
            return env

        env["HOME"] = user_entry.pw_dir
        env["USER"] = user_entry.pw_name
        env["LOGNAME"] = user_entry.pw_name
        return env

    def current_user_entry(self):
        try:
            return pwd.getpwuid(os.getuid())
        except KeyError:
            return None

    def is_executable_file(self, path):
        candidate = Path(path)
        return candidate.is_file() and os.access(str(candidate), os.X_OK)

    def resolve_uv_executable(self):
        configured_value = os.environ.get("VIDEO_PORTAL_UV_BIN")
        checked_locations = []
        user_entry = self.current_user_entry()
        user_name = user_entry.pw_name if user_entry is not None else str(os.getuid())
        subprocess_env = self.build_subprocess_env()
        search_path = subprocess_env.get("PATH")

        if configured_value:
            configured_path = Path(configured_value).expanduser()
            checked_locations.append(str(configured_path))

            if os.sep in configured_value or configured_path.is_absolute():
                if not configured_path.exists():
                    raise UpdateError(
                        "Configured uv executable does not exist: %s. Set "
                        "VIDEO_PORTAL_UV_BIN to a usable executable."
                        % configured_path
                    )
                if not self.is_executable_file(configured_path):
                    raise UpdateError(
                        "Configured uv executable is not executable by %s: %s. "
                        "Set VIDEO_PORTAL_UV_BIN to a usable executable."
                        % (user_name, configured_path)
                    )
                return str(configured_path)

            resolved_path = shutil.which(configured_value, path=search_path)
            if resolved_path:
                return resolved_path
            raise UpdateError(
                "Configured uv executable was not found in PATH: %s. Set "
                "VIDEO_PORTAL_UV_BIN to a usable executable path."
                % configured_value
            )

        for candidate in (Path("/usr/local/bin/uv"),):
            checked_locations.append(str(candidate))
            if self.is_executable_file(candidate):
                return str(candidate)

        if user_entry is not None:
            user_local_candidate = Path(user_entry.pw_dir) / ".local" / "bin" / "uv"
            checked_locations.append(str(user_local_candidate))
            if self.is_executable_file(user_local_candidate):
                return str(user_local_candidate)

        resolved_path = shutil.which("uv", path=search_path)
        if resolved_path:
            checked_locations.append(resolved_path)
            return resolved_path

        raise UpdateError(
            "Could not find a usable uv executable. Checked: %s. Set "
            "VIDEO_PORTAL_UV_BIN to a usable executable path."
            % ", ".join(checked_locations)
        )

    def ensure_layout(self):
        for path in (
            self.releases_dir,
            self.failed_releases_dir,
            self.incoming_dir,
            self.staging_dir,
            self.logs_dir,
            self.updater_dir,
            self.shared_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self.save_state(dict(DEFAULT_STATE))

    def log(self, message, *args):
        if args:
            message = message % args
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        line = "[%s] %s" % (timestamp, message)
        print(line)
        if self._log_handle is not None:
            self._log_handle.write(line + "\n")
            self._log_handle.flush()

    @contextlib.contextmanager
    def locked(self):
        with self.lock_path.open("w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield

    def load_state(self):
        if not self.state_path.exists():
            return dict(DEFAULT_STATE)
        with self.state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        merged = dict(DEFAULT_STATE)
        merged.update(state)
        return merged

    def save_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, self.state_path)

    def run_command(self, parts, cwd=None, check=True, env=None):
        command = list(parts)
        self.log("Running command: %s", " ".join(command))
        command_env = self.build_subprocess_env()
        if env:
            command_env.update(env)
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            env=command_env,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            self.log("stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            self.log("stderr: %s", result.stderr.strip())
        if check and result.returncode != 0:
            raise UpdateError(
                "Command failed (%s): %s" % (result.returncode, " ".join(command))
            )
        return result

    def run_privileged_command(self, parts, check=True):
        command = ["sudo"] + list(parts) if self.use_sudo else list(parts)
        return self.run_command(command, check=check)

    def discover_active_release(self):
        if self.current_path.is_symlink():
            try:
                resolved = self.current_path.resolve()
            except FileNotFoundError:
                return None
            return resolved.name
        return None

    def find_newest_package(self):
        packages = sorted(self.incoming_dir.glob("*.zip"))
        if not packages:
            return None
        return max(packages, key=lambda candidate: candidate.stat().st_mtime)

    def make_attempt_id(self):
        return datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")

    def begin_attempt_logging(self, attempt_id):
        log_path = self.logs_dir / ("update-%s.log" % attempt_id)
        self._log_handle = log_path.open("a", encoding="utf-8")
        self.log("Starting update attempt %s", attempt_id)
        return log_path

    def end_attempt_logging(self):
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def recover_interrupted_update(self, state):
        if not state.get("update_in_progress"):
            return state

        self.log("Detected interrupted update state, attempting recovery.")
        last_known_good = state.get("last_known_good")
        active_release = state.get("active_release")

        if last_known_good and active_release and active_release != last_known_good:
            self.rollback_to_release(
                last_known_good,
                failed_release=active_release,
                state=state,
                reason="Recovered from interrupted update.",
            )
        else:
            state["update_in_progress"] = False
            state["last_error"] = "Cleared stale in-progress state during recovery."
            self.save_state(state)
        return self.load_state()

    def move_package_to_attempt_dir(self, package_path, attempt_id):
        attempt_dir = self.staging_dir / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=True)
        target = attempt_dir / "package.zip"
        shutil.move(str(package_path), str(target))
        return attempt_dir, target

    def load_manifest(self, staging_root):
        manifest_path = staging_root / "manifest.json"
        if not manifest_path.exists():
            raise UpdateError("Update package is missing manifest.json.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        required_fields = (
            "package_layout_version",
            "version",
            "python",
            "entrypoint",
            "project_root",
            "uv_cache",
            "healthcheck_url",
            "files",
        )
        missing = [field for field in required_fields if field not in manifest]
        if missing:
            raise UpdateError(
                "Manifest is missing required fields: %s" % ", ".join(missing)
            )

        if manifest["package_layout_version"] != PACKAGE_LAYOUT_VERSION:
            raise UpdateError(
                "Unsupported package layout version: %s"
                % manifest["package_layout_version"]
            )
        if not isinstance(manifest["files"], dict) or not manifest["files"]:
            raise UpdateError("Manifest must include file hashes.")

        for relative_path in list(manifest["files"].keys()) + [
            manifest["entrypoint"],
            manifest["project_root"],
            manifest["uv_cache"],
        ]:
            path = PurePosixPath(relative_path)
            if path.is_absolute() or any(part == ".." for part in path.parts):
                raise UpdateError(
                    "Manifest contains an invalid path: %s" % relative_path
                )

        if not (staging_root / "VERSION").exists():
            raise UpdateError("Update package is missing VERSION.")
        for relative_name in PROJECT_LAYOUT_DIRS:
            if not (staging_root / relative_name).is_dir():
                raise UpdateError(
                    "Update package is missing %s/ contents." % relative_name
                )
        if not (staging_root / manifest["uv_cache"]).is_dir():
            raise UpdateError("Update package is missing uv cache contents.")

        if not (staging_root / manifest["entrypoint"]).exists():
            raise UpdateError("Manifest entrypoint does not exist in the package.")
        project_root = staging_root / manifest["project_root"]
        for relative_name in PROJECT_METADATA_ENTRIES:
            if not (project_root / relative_name).exists():
                raise UpdateError(
                    "Update package is missing project metadata file: %s"
                    % relative_name
                )
        return manifest

    def verify_manifest_files(self, staging_root, manifest):
        self.log("Verifying manifest hashes.")
        for relative_path, expected_hash in sorted(manifest["files"].items()):
            target = staging_root / Path(relative_path)
            if not target.exists():
                raise UpdateError(
                    "Manifest references missing file: %s" % relative_path
                )
            actual_hash = sha256_file(target)
            if actual_hash != expected_hash:
                raise UpdateError("Hash mismatch for %s" % relative_path)

    def extract_package(self, package_path, extracted_root):
        self.log("Extracting update package %s", package_path)
        extracted_root.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(package_path) as archive:
                archive.extractall(str(extracted_root))
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise UpdateError("Could not extract update package: %s" % exc)

    def build_release_id(self, manifest, version_text):
        raw_version = manifest.get("version") or version_text or "unknown"
        safe_version = "".join(
            ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in raw_version
        )
        return "%s_%s" % (datetime.utcnow().strftime("%Y-%m-%d_%H%M%S"), safe_version)

    def create_release(self, staging_root, manifest, release_id):
        release_dir = self.releases_dir / release_id
        if release_dir.exists():
            raise UpdateError("Release directory already exists: %s" % release_dir)

        self.log("Creating release directory %s", release_dir)
        shutil.copytree(staging_root, release_dir)

        self.apply_shared_overlay(release_dir)
        self.install_dependencies(release_dir, manifest)
        return release_dir

    def apply_shared_overlay(self, release_dir):
        ensure_shared_dir(self.portal_root)
        try:
            overlay_shared_tree(self.shared_dir, release_dir)
        except RuntimeError as exc:
            raise UpdateError(str(exc))

    def iter_migration_scripts(self, release_dir, phase):
        phase_dir = release_dir / "scripts" / phase
        if not phase_dir.exists():
            return

        for script_path in sorted(phase_dir.iterdir()):
            if script_path.name.startswith(".") or not script_path.is_file():
                continue
            match = MIGRATION_SCRIPT_PATTERN.match(script_path.name)
            if not match:
                raise UpdateError(
                    "Invalid %s migration name: %s" % (phase, script_path.name)
                )
            yield match.group("version"), script_path

    def run_migration_script(
        self, phase, version, script_path, release_dir, manifest, previous_release
    ):
        self.log("Executing %s migration %s", phase, script_path.name)
        env = self.build_subprocess_env()
        env.update(
            {
                "VIDEO_PORTAL_RELEASE_DIR": str(release_dir),
                "VIDEO_PORTAL_PORTAL_ROOT": str(self.portal_root),
                "VIDEO_PORTAL_VERSION": manifest["version"],
                "VIDEO_PORTAL_PHASE": phase,
                "VIDEO_PORTAL_PREVIOUS_RELEASE": previous_release or "",
                "VIDEO_PORTAL_MIGRATION_VERSION": version,
            }
        )
        result = subprocess.run(
            ["/bin/bash", str(script_path)],
            cwd=str(release_dir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            self.log("stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            self.log("stderr: %s", result.stderr.strip())
        if result.returncode != 0:
            raise UpdateError("%s migration failed: %s" % (phase, script_path.name))

    def run_migration_phase(self, phase, release_dir, manifest, previous_release, state):
        state_field = MIGRATION_STATE_FIELDS[phase]
        last_successful = state.get(state_field)

        for version, script_path in self.iter_migration_scripts(release_dir, phase) or ():
            if last_successful and version <= str(last_successful):
                continue

            self.run_migration_script(
                phase,
                version,
                script_path,
                release_dir,
                manifest,
                previous_release,
            )
            state[state_field] = version
            self.save_state(state)
            last_successful = version

    def install_dependencies(self, release_dir, manifest):
        uv_cache_path = release_dir / "uv-cache"
        self.run_command(
            [
                self.uv_executable,
                "sync",
                "--project",
                str(release_dir),
                "--python",
                manifest["python"],
                "--frozen",
                "--offline",
                "--no-dev",
                "--no-install-project",
                "--cache-dir",
                str(uv_cache_path),
            ],
            env={
                "UV_MANAGED_PYTHON": "true",
                "UV_PYTHON_INSTALL_DIR": self.uv_python_install_dir,
            },
        )

    def switch_current_symlink(self, target_release_dir):
        if self.current_path.exists() and not self.current_path.is_symlink():
            raise UpdateError(
                "Current release path must be a symlink: %s" % self.current_path
            )

        temporary_link = self.portal_root / "current.new"
        if temporary_link.exists() or temporary_link.is_symlink():
            temporary_link.unlink()
        temporary_link.symlink_to(target_release_dir)
        os.replace(str(temporary_link), str(self.current_path))
        self.log("Switched current symlink to %s", target_release_dir)

    def iter_restart_programs(self, manifest):
        seen = set()
        candidates = [self.app_program_name]
        candidates.extend(manifest.get("supervisor_programs", []))

        for candidate in candidates:
            program = str(candidate).strip()
            if not program or program in seen:
                continue
            seen.add(program)
            yield program

    def restart_app_program(self):
        self.run_privileged_command(["supervisorctl", "restart", self.app_program_name])

    def restart_supervisor_programs(self, manifest):
        for program in self.iter_restart_programs(manifest):
            should_check = program == self.app_program_name
            result = self.run_privileged_command(
                ["supervisorctl", "restart", program], check=should_check
            )
            if result.returncode != 0:
                self.log("Supervisor restart failed for %s; continuing.", program)

    def verify_service_active(self):
        result = self.run_privileged_command(
            ["supervisorctl", "status", self.app_program_name],
            check=False,
        )
        status_line = result.stdout.strip() or result.stderr.strip()
        parts = status_line.split()
        return len(parts) >= 2 and parts[1] == "RUNNING"

    def fetch_healthcheck(self, url):
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def wait_for_healthcheck(self, url, expected_version):
        deadline = time.monotonic() + self.healthcheck_timeout
        last_error = None
        while time.monotonic() < deadline:
            if not self.verify_service_active():
                last_error = "supervisor program is not running"
                self.sleep(self.healthcheck_interval)
                continue

            try:
                payload = self.fetch_healthcheck(url)
                if payload.get("status") == "ok" and str(payload.get("version")) == str(
                    expected_version
                ):
                    self.log("Healthcheck passed for version %s", expected_version)
                    return payload
                last_error = "healthcheck returned unexpected payload: %s" % payload
            except (urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
                last_error = str(exc)

            self.sleep(self.healthcheck_interval)

        raise HealthCheckError(
            last_error or "healthcheck did not succeed before timeout"
        )

    def preserve_failed_release(self, failed_release):
        if not failed_release:
            return
        failed_path = self.releases_dir / failed_release
        if not failed_path.exists():
            return

        self.failed_releases_dir.mkdir(parents=True, exist_ok=True)
        target = self.failed_releases_dir / failed_release
        if target.exists():
            target = self.failed_releases_dir / (
                "%s-%s" % (failed_release, self.make_attempt_id())
            )
        shutil.move(str(failed_path), str(target))
        self.log("Preserved failed release at %s", target)

    def read_release_version(self, release_name):
        version_path = self.releases_dir / release_name / "VERSION"
        if not version_path.exists():
            return None
        return version_path.read_text(encoding="utf-8").strip()

    def rollback_to_release(
        self, release_name, failed_release=None, state=None, reason=None, manifest=None
    ):
        state = state or self.load_state()
        target_release_dir = self.releases_dir / release_name
        if not (target_release_dir / "app").exists():
            raise UpdateError(
                "Rollback target release does not exist: %s" % release_name
            )

        self.switch_current_symlink(target_release_dir)
        rollback_manifest = manifest
        if rollback_manifest is None:
            manifest_path = self.releases_dir / release_name / "manifest.json"
            if manifest_path.exists():
                rollback_manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
        if rollback_manifest:
            self.restart_supervisor_programs(rollback_manifest)
        else:
            self.restart_app_program()

        expected_version = self.read_release_version(release_name)
        manifest_url = None
        manifest_path = self.releases_dir / release_name / "manifest.json"
        if manifest_path.exists():
            manifest_url = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "healthcheck_url"
            )
        if manifest_url and expected_version:
            self.wait_for_healthcheck(manifest_url, expected_version)

        self.preserve_failed_release(failed_release)
        state["active_release"] = release_name
        state["previous_release"] = failed_release
        state["last_known_good"] = release_name
        state["update_in_progress"] = False
        state["last_error"] = reason
        self.save_state(state)
        self.log("Rollback to %s completed.", release_name)

    def process_package(self, package_path, state, attempt_id):
        state["last_attempt"] = attempt_id
        state["last_error"] = None
        self.save_state(state)

        staging_root, staged_package = self.move_package_to_attempt_dir(
            package_path, attempt_id
        )
        extracted_root = staging_root / "extracted"
        self.extract_package(staged_package, extracted_root)

        manifest = self.load_manifest(extracted_root)
        self.verify_manifest_files(extracted_root, manifest)

        version_text = (extracted_root / "VERSION").read_text(encoding="utf-8").strip()
        release_id = self.build_release_id(manifest, version_text)
        previous_release = state.get("active_release") or self.discover_active_release()
        release_dir = self.create_release(extracted_root, manifest, release_id)
        self.run_migration_phase(
            "predeploy", release_dir, manifest, previous_release, state
        )

        state["previous_release"] = previous_release
        state["active_release"] = release_id
        state["update_in_progress"] = True
        self.save_state(state)

        try:
            self.switch_current_symlink(release_dir)
            self.restart_supervisor_programs(manifest)
            self.wait_for_healthcheck(manifest["healthcheck_url"], version_text)
            self.run_migration_phase(
                "postdeploy", release_dir, manifest, previous_release, state
            )
            self.wait_for_healthcheck(manifest["healthcheck_url"], version_text)
        except Exception as exc:
            self.log("Update failed after switch: %s", exc)
            if previous_release:
                self.rollback_to_release(
                    previous_release,
                    failed_release=release_id,
                    state=state,
                    reason=str(exc),
                    manifest=manifest,
                )
            else:
                self.preserve_failed_release(release_id)
                state["update_in_progress"] = False
                state["last_error"] = str(exc)
                self.save_state(state)
            raise

        state["last_known_good"] = release_id
        state["active_release"] = release_id
        state["previous_release"] = previous_release
        state["update_in_progress"] = False
        state["last_error"] = None
        self.save_state(state)
        self.log("Update completed successfully. Active release is now %s", release_id)
        return release_id

    def run(self):
        self.ensure_layout()
        with self.locked():
            state = self.load_state()
            state = self.recover_interrupted_update(state)

            package_path = self.find_newest_package()
            if package_path is None:
                self.begin_attempt_logging("idle")
                try:
                    self.log("No update packages found in %s", self.incoming_dir)
                finally:
                    self.end_attempt_logging()
                return 0

            attempt_id = self.make_attempt_id()
            self.begin_attempt_logging(attempt_id)
            try:
                self.process_package(package_path, state, attempt_id)
            except (UpdateError, HealthCheckError, subprocess.SubprocessError) as exc:
                self.log("Update attempt %s failed: %s", attempt_id, exc)
                state = self.load_state()
                state["update_in_progress"] = False
                state["last_attempt"] = attempt_id
                state["last_error"] = str(exc)
                self.save_state(state)
                return 1
            finally:
                self.end_attempt_logging()
        return 0


def main():
    updater = Updater()
    return updater.run()


if __name__ == "__main__":
    sys.exit(main())
