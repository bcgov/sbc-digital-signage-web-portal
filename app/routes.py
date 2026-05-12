import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)
from werkzeug.utils import secure_filename

main_bp = Blueprint("main", __name__)

UPDATE_IN_PROGRESS_MESSAGE = "Updating software"
UPDATE_SUCCESS_MESSAGE = "Update successful"
UPDATE_FAILURE_MESSAGE = (
    "Update failed. Please contact SBCTS@gov.bc.ca for assistance"
)
UPDATE_SUCCESS_LOG_MARKER = "Update completed successfully."


def require_admin_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if (
            not auth
            or auth.username != current_app.config.get("VIDEO_PORTAL_ADMIN_USERNAME")
            or auth.password != current_app.config.get("VIDEO_PORTAL_ADMIN_PASSWORD")
        ):
            return ("", 401, {"WWW-Authenticate": 'Basic realm="Admin Console"'})
        return f(*args, **kwargs)
    return decorated


def get_recent_update_log(log_dir):
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return None, []

    log_files = sorted(log_dir.glob("update-*.log"))
    if not log_files:
        return None, []

    latest_log = log_files[-1]
    lines = latest_log.read_text(encoding="utf-8", errors="replace").splitlines()
    return latest_log.name, lines[-20:]


def load_update_status():
    state_path = Path(current_app.config["UPDATER_STATE_FILE"])
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {
            "active_release": None,
            "last_known_good": None,
            "last_successful_postdeploy_migration": None,
            "last_successful_predeploy_migration": None,
            "previous_release": None,
            "update_in_progress": False,
            "last_attempt": None,
            "last_error": None,
        }

    log_name, log_lines = get_recent_update_log(current_app.config["UPDATE_LOG_DIR"])
    state["latest_log"] = log_name
    state["log_tail"] = log_lines
    return state


def classify_update_result(status):
    if status.get("update_in_progress"):
        return "in_progress"
    if not status.get("last_attempt"):
        return "idle"
    if status.get("last_error"):
        return "failed"
    log_tail = status.get("log_tail") or []
    if any(UPDATE_SUCCESS_LOG_MARKER in line for line in log_tail):
        return "succeeded"
    return "pending"


def build_admin_notice(status, update_requested=False):
    if update_requested or status.get("update_in_progress"):
        return {
            "kind": "info",
            "message": UPDATE_IN_PROGRESS_MESSAGE,
            "show_progress": True,
        }

    result = classify_update_result(status)
    if result == "succeeded":
        return {
            "kind": "success",
            "message": UPDATE_SUCCESS_MESSAGE,
            "show_progress": False,
        }
    if result in {"in_progress", "pending"}:
        return {
            "kind": "info",
            "message": UPDATE_IN_PROGRESS_MESSAGE,
            "show_progress": True,
        }
    if result == "failed":
        return {
            "kind": "error",
            "message": UPDATE_FAILURE_MESSAGE,
            "show_progress": False,
        }

    return None


def start_update_service():
    command = [
        "sudo",
        "supervisorctl",
        "start",
        current_app.config["UPDATE_PROGRAM_NAME"],
    ]
    current_app.logger.info(
        "Starting updater service with command: %s", " ".join(command)
    )

    if platform.system() != "Linux":
        current_app.logger.info(
            "[TEST MODE - %s] Would execute: %s",
            platform.system(),
            " ".join(command),
        )
        return True, "Updater service start simulated on non-Linux host."

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out while starting updater service."
    except Exception as exc:  # pragma: no cover - defensive logging
        return False, str(exc)

    if result.returncode != 0:
        output = "\n".join(
            part for part in (result.stdout.strip(), result.stderr.strip()) if part
        ).strip()
        if "already started" in output.lower():
            return True, "Update program is already running."
        stderr = output or "unknown error"
        return False, stderr

    return True, "Update program started."


@main_bp.route("/")
def index():
    client_ip = request.remote_addr
    current_app.logger.info("Portal accessed from %s", client_ip)
    return render_template("upload.html")


@main_bp.route("/healthz")
def healthz():
    return jsonify(
        {
            "status": "ok",
            "version": current_app.config["APP_VERSION"],
            "release": current_app.config["APP_RELEASE_ID"],
        }
    )


@main_bp.route("/current-video")
def current_video():
    filepath = Path(current_app.config["UPLOAD_FOLDER"]) / "SBC-DISPLAY-VIDEO.mp4"
    if not filepath.is_file():
        abort(404, description="Current video not found")

    return send_file(filepath, mimetype="video/mp4", conditional=True)


@main_bp.route("/upload", methods=["POST"])
def upload():
    client_ip = request.remote_addr

    if "video" not in request.files:
        current_app.logger.warning(
            "Upload attempt without video file from %s", client_ip
        )
        return jsonify({"error": "No video file"}), 400

    file = request.files["video"]
    if file.filename == "":
        current_app.logger.warning(
            "Upload attempt with empty filename from %s", client_ip
        )
        return jsonify({"error": "No selected file"}), 400

    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    file_size_mb = file_size / (1024 * 1024)

    filepath = Path(current_app.config["UPLOAD_FOLDER"]) / "SBC-DISPLAY-VIDEO.mp4"
    file.save(filepath)

    current_app.logger.info(
        "Video uploaded successfully from %s | Original: %s | Size: %.2f MB | Saved as: %s",
        client_ip,
        file.filename,
        file_size_mb,
        filepath.name,
    )

    try:
        system = platform.system()
        command = ["sudo", "supervisorctl", "restart", "video_looper"]
        if system == "Linux":
            result = subprocess.run(
                command, capture_output=True, timeout=5, text=True, check=False
            )
            if result.returncode == 0:
                current_app.logger.info(
                    "Video looper service restarted successfully to load new video"
                )
            else:
                current_app.logger.warning(
                    "Video looper restart returned code %s: %s",
                    result.returncode,
                    result.stderr,
                )
        else:
            current_app.logger.info(
                "[TEST MODE - %s] Would execute: %s", system, " ".join(command)
            )
    except subprocess.TimeoutExpired:
        current_app.logger.warning("Video player restart timed out")
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning("Could not restart video player: %s", exc)

    return jsonify({"success": True, "message": "Video uploaded successfully"})


@main_bp.route("/restart", methods=["POST"])
def restart():
    client_ip = request.remote_addr
    current_app.logger.warning("TV restart requested from %s", client_ip)

    try:
        system = platform.system()
        if system == "Linux":
            current_app.logger.info("Executing system reboot...")
            subprocess.Popen(["sudo", "reboot"])
            return jsonify({"success": True, "message": "System restart initiated"})

        current_app.logger.info(
            "Restart requested but skipped (running on %s, not Raspberry Pi)", system
        )
        return jsonify(
            {"success": True, "message": f"Restart simulated (running on {system})"}
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.error("Restart failed from %s: %s", client_ip, exc)
        return jsonify({"error": "Restart failed", "details": str(exc)}), 500


@main_bp.route("/admin", methods=["GET", "POST"])
@require_admin_auth
def admin_console():
    status = load_update_status()
    initial_last_attempt = status.get("last_attempt")
    error = None
    update_requested = False

    if request.method == "POST":
        upload_file = request.files.get("update_zip")
        if (
            upload_file is None
            or upload_file.filename == ""
            or upload_file.filename is None
        ):
            error = "Select a .zip update package."
        elif not upload_file.filename.lower().endswith(".zip"):
            error = "Only .zip update packages are supported."
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_name = secure_filename(upload_file.filename)
            target_name = f"{timestamp}-{safe_name}"
            incoming_path = (
                Path(current_app.config["UPDATE_INCOMING_DIR"]) / target_name
            )
            upload_file.save(incoming_path)
            current_app.logger.info("Saved update package to %s", incoming_path)

            started, detail = start_update_service()
            if started:
                update_requested = True
                status = load_update_status()
            else:
                error = f"Package uploaded to {incoming_path.name}, but the updater could not start: {detail}"

    update_notice = build_admin_notice(status, update_requested=update_requested)

    return render_template(
        "admin.html",
        status=status,
        update_notice=update_notice,
        error_message=error,
        status_endpoint="/status",
        watch_update=update_requested or status.get("update_in_progress", False),
        initial_last_attempt=initial_last_attempt or "",
        initial_active_release=status.get("active_release") or "",
    )


@main_bp.route("/status")
@require_admin_auth
def admin_status():
    return jsonify(load_update_status())
