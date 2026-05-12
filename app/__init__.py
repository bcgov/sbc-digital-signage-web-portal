import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PORTAL_ROOT = Path("/home/pi/video-portal")
DEFAULT_UPLOAD_FOLDER = "/home/pi/videos"
DEFAULT_MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2GB
DEFAULT_UPDATE_PROGRAM = "video-portal-update"
DEFAULT_APP_PROGRAM = "video-portal"
DEFAULT_HEALTHCHECK_PATH = "/healthz"


def get_bool_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"true", "1", "yes", "on"}


def get_int_env(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def discover_portal_root():
    configured_root = os.environ.get("VIDEO_PORTAL_ROOT")
    if configured_root:
        return Path(configured_root).expanduser()

    candidates = (
        BASE_DIR,
        BASE_DIR.parent,
        DEFAULT_PORTAL_ROOT,
    )
    for candidate in candidates:
        if (candidate / "updates").exists():
            return candidate
    return BASE_DIR


def read_app_version(base_dir=None):
    base_dir = Path(base_dir or BASE_DIR)
    configured_version = os.environ.get("APP_VERSION")
    if configured_version:
        return configured_version

    candidates = (
        base_dir / "VERSION",
        base_dir.parent / "VERSION",
        BASE_DIR / "VERSION",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip() or "dev"
    return "dev"


def get_release_id(base_dir=None):
    base_dir = Path(base_dir or BASE_DIR)
    if (base_dir.parent / "manifest.json").exists():
        return base_dir.parent.name
    return os.environ.get("VIDEO_PORTAL_RELEASE", "development")


def get_app_config():
    load_dotenv(BASE_DIR / ".env")

    portal_root = discover_portal_root()
    updates_root = Path(
        os.environ.get("VIDEO_PORTAL_UPDATES_ROOT", portal_root / "updates")
    )
    updater_root = Path(
        os.environ.get("VIDEO_PORTAL_UPDATER_ROOT", portal_root / "updater")
    )
    log_dir = Path(os.environ.get("VIDEO_PORTAL_LOG_DIR", portal_root / "logs"))

    config = {
        "HOST": os.environ.get("FLASK_HOST", "0.0.0.0"),
        "PORT": get_int_env("FLASK_PORT", 80),
        "DEBUG": get_bool_env("FLASK_DEBUG", default=False),
        "UPLOAD_FOLDER": os.environ.get("UPLOAD_FOLDER", DEFAULT_UPLOAD_FOLDER),
        "MAX_CONTENT_LENGTH": get_int_env(
            "MAX_CONTENT_LENGTH",
            DEFAULT_MAX_CONTENT_LENGTH,
        ),
        "PORTAL_ROOT": portal_root,
        "UPDATES_ROOT": updates_root,
        "UPDATE_INCOMING_DIR": updates_root / "incoming",
        "UPDATE_STAGING_DIR": updates_root / "staging",
        "UPDATE_LOG_DIR": updates_root / "logs",
        "APP_LOG_DIR": log_dir,
        "UPDATER_ROOT": updater_root,
        "UPDATER_STATE_FILE": updater_root / "state.json",
        "UPDATE_PROGRAM_NAME": os.environ.get(
            "VIDEO_PORTAL_UPDATE_PROGRAM",
            DEFAULT_UPDATE_PROGRAM,
        ),
        "APP_PROGRAM_NAME": os.environ.get(
            "VIDEO_PORTAL_APP_PROGRAM",
            DEFAULT_APP_PROGRAM,
        ),
        "APP_VERSION": read_app_version(),
        "APP_RELEASE_ID": get_release_id(),
        "HEALTHCHECK_PATH": os.environ.get(
            "VIDEO_PORTAL_HEALTHCHECK_PATH",
            DEFAULT_HEALTHCHECK_PATH,
        ),
        "VIDEO_PORTAL_ADMIN_USERNAME": os.environ.get(
            "VIDEO_PORTAL_ADMIN_USERNAME",
            "",
        ),
        "VIDEO_PORTAL_ADMIN_PASSWORD": os.environ.get(
            "VIDEO_PORTAL_ADMIN_PASSWORD",
            "",
        ),
    }
    return config


def configure_logging(app):
    log_dir = Path(app.config["APP_LOG_DIR"])
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("video_portal")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_file = log_dir / "video_portal.log"
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S %Z",
    )

    existing_handler = None
    stale_handlers = []
    for handler in logger.handlers:
        if (
            isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename) == log_file
        ):
            existing_handler = handler
        elif isinstance(handler, RotatingFileHandler):
            stale_handlers.append(handler)

    for handler in stale_handlers:
        logger.removeHandler(handler)
        handler.close()

    if existing_handler is None:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)


def create_app(test_config=None):
    app = Flask(__name__)
    config = get_app_config()
    if test_config:
        config.update(test_config)

    app.config.update(config)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPDATE_INCOMING_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPDATE_STAGING_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPDATE_LOG_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPDATER_ROOT"]).mkdir(parents=True, exist_ok=True)

    configure_logging(app)

    from .routes import main_bp

    app.register_blueprint(main_bp)

    return app
