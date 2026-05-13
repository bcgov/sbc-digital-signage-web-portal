#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

PORTAL_USER=${VIDEO_PORTAL_USER:-pi}
PORTAL_ROOT=${VIDEO_PORTAL_ROOT:-/home/pi/video-portal}
CURRENT_ROOT="$PORTAL_ROOT/current"
PORTAL_USER_HOME=

SKIP_SUPERVISOR_CONTROL=${VIDEO_PORTAL_SKIP_SUPERVISOR_CONTROL:-false}
VIDEO_PORTAL_ADMIN_USERNAME=${VIDEO_PORTAL_ADMIN_USERNAME:-admin}
VIDEO_PORTAL_ADMIN_PASSWORD=${VIDEO_PORTAL_ADMIN_PASSWORD:-}

UV_BIN=${VIDEO_PORTAL_UV_BIN:-/usr/local/bin/uv}
UV_CACHE_DIR="$PORTAL_ROOT/.uv/cache"
UV_PYTHON_INSTALL_DIR="$PORTAL_ROOT/.uv/python"
PROJECT_PYTHON_VERSION=$(cat "$SOURCE_ROOT/.python-version")
export UV_CACHE_DIR UV_PYTHON_INSTALL_DIR

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "Run this script as root, for example: sudo ./scripts/provision.sh" >&2
        exit 1
    fi
}

require_admin_password() {
    if [ -z "$VIDEO_PORTAL_ADMIN_PASSWORD" ]; then
        echo "Set VIDEO_PORTAL_ADMIN_PASSWORD in the environment before running provision.sh." >&2
        echo "Example: sudo VIDEO_PORTAL_ADMIN_PASSWORD='change-me' ./scripts/provision.sh" >&2
        exit 1
    fi
}

resolve_portal_user_home() {
    if command -v getent >/dev/null 2>&1; then
        home_dir=$(getent passwd "$PORTAL_USER" | cut -d: -f6)
        if [ -n "$home_dir" ]; then
            printf '%s\n' "$home_dir"
            return
        fi
    fi

    home_dir=$(python3 - "$PORTAL_USER" <<'PY'
import pwd
import sys

try:
    print(pwd.getpwnam(sys.argv[1]).pw_dir)
except KeyError:
    sys.exit(1)
PY
    ) || {
        echo "Could not determine home directory for $PORTAL_USER" >&2
        exit 1
    }

    printf '%s\n' "$home_dir"
}

run_as_portal_user() {
    sudo -H -u "$PORTAL_USER" env \
        HOME="$PORTAL_USER_HOME" \
        USER="$PORTAL_USER" \
        LOGNAME="$PORTAL_USER" \
        UV_CACHE_DIR="$UV_CACHE_DIR" \
        UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
        "$@"
}

portal_user_can_execute() {
    run_as_portal_user sh -c 'test -x "$1"' sh "$1"
}

install_system_packages() {
    export DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-noninteractive}
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libcap2-bin \
        python3 \
        sudo \
        supervisor
}

ensure_directories() {
    mkdir -p \
        "$PORTAL_ROOT" \
        /home/pi/videos \
        "$PORTAL_ROOT/logs" \
        "$PORTAL_ROOT/shared/app" \
        "$PORTAL_ROOT/updates/incoming" \
        "$PORTAL_ROOT/updates/logs" \
        "$PORTAL_ROOT/updates/staging" \
        "$PORTAL_ROOT/updater" \
        "$PORTAL_ROOT/.uv" \
        /etc/supervisor/conf.d \
        /etc/sudoers.d
}

write_shared_env() {
    run_as_portal_user env \
        VIDEO_PORTAL_ADMIN_USERNAME="$VIDEO_PORTAL_ADMIN_USERNAME" \
        VIDEO_PORTAL_ADMIN_PASSWORD="$VIDEO_PORTAL_ADMIN_PASSWORD" \
        sh -c 'cat > "$1" <<EOF
FLASK_HOST=0.0.0.0
FLASK_PORT=80
FLASK_DEBUG=false
UPLOAD_FOLDER=/home/pi/videos
MAX_CONTENT_LENGTH=2147483648
VIDEO_PORTAL_ADMIN_USERNAME=$VIDEO_PORTAL_ADMIN_USERNAME
VIDEO_PORTAL_ADMIN_PASSWORD=$VIDEO_PORTAL_ADMIN_PASSWORD
EOF
    ' sh "$PORTAL_ROOT/shared/app/.env"
}

seed_release_layout() {
    if [ -e "$CURRENT_ROOT" ]; then
        return
    fi

    python3 "$SOURCE_ROOT/tools/migrate_release.py" --portal-root "$PORTAL_ROOT"
}

ensure_current_env_link() {
    if [ ! -e "$CURRENT_ROOT" ]; then
        return
    fi

    run_as_portal_user mkdir -p "$CURRENT_ROOT/app"
    run_as_portal_user ln -sfn "../../../shared/app/.env" "$CURRENT_ROOT/app/.env"
}

seed_virtualenv() {
    run_as_portal_user "$UV_BIN" python install "$PROJECT_PYTHON_VERSION"
    run_as_portal_user "$UV_BIN" sync \
        --project "$CURRENT_ROOT" \
        --python "$PROJECT_PYTHON_VERSION" \
        --frozen \
        --no-dev \
        --no-install-project
}

install_uv() {
    PORTAL_USER_HOME=${PORTAL_USER_HOME:-$(resolve_portal_user_home)}
    portal_user_uv="$PORTAL_USER_HOME/.local/bin/uv"
    portal_user_uvx="$PORTAL_USER_HOME/.local/bin/uvx"

    if portal_user_can_execute "$UV_BIN" && portal_user_can_execute "$portal_user_uv"; then
        return
    fi

    run_as_portal_user mkdir -p "$PORTAL_USER_HOME/.local/bin"
    run_as_portal_user sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

    if ! portal_user_can_execute "$portal_user_uv"; then
        echo "uv installation did not produce $portal_user_uv" >&2
        exit 1
    fi

    ln -sf "$portal_user_uv" "$UV_BIN"
    if portal_user_can_execute "$portal_user_uvx"; then
        ln -sf "$portal_user_uvx" /usr/local/bin/uvx
    fi

    if ! portal_user_can_execute "$UV_BIN"; then
        echo "$UV_BIN is not executable by $PORTAL_USER after installation" >&2
        exit 1
    fi
}

install_supervisor_programs() {
    install -m 644 \
        "$SOURCE_ROOT/deploy/supervisor/video-portal.conf" \
        /etc/supervisor/conf.d/video-portal.conf
    install -m 644 \
        "$SOURCE_ROOT/deploy/supervisor/video-portal-update.conf" \
        /etc/supervisor/conf.d/video-portal-update.conf
}

install_sudoers() {
    install -m 440 \
        "$SOURCE_ROOT/deploy/sudoers/video-portal-update" \
        /etc/sudoers.d/video-portal-update
}

grant_low_port_access() {
    real_python=$("$CURRENT_ROOT/.venv/bin/python" -c 'import os, sys; print(os.path.realpath(sys.executable))')
    setcap 'cap_net_bind_service=+ep' "$real_python"
    capability_text=$(getcap "$real_python" 2>/dev/null || true)
    case "$capability_text" in
        *cap_net_bind_service=ep*|*cap_net_bind_service+ep*)
            ;;
        *)
            echo "Failed to verify cap_net_bind_service on $real_python" >&2
            if [ -n "$capability_text" ]; then
                echo "Current capability output: $capability_text" >&2
            fi
            exit 1
            ;;
    esac
}

fix_ownership() {
    chown -R "$PORTAL_USER:$PORTAL_USER" "$PORTAL_ROOT" /home/pi/videos
}

supervisor_control_is_skipped() {
    case "$SKIP_SUPERVISOR_CONTROL" in
        1|true|yes|on)
            return 0
            ;;
    esac
    return 1
}

supervisor_service_is_running() {
    if command -v service >/dev/null 2>&1; then
        service supervisor status >/dev/null 2>&1
        return $?
    fi
    if command -v systemctl >/dev/null 2>&1; then
        systemctl is-active --quiet "supervisor"
        return $?
    fi
    return 1
}

stop_supervisor_service() {
    if supervisor_control_is_skipped; then
        echo "Skipping supervisor stop because VIDEO_PORTAL_SKIP_SUPERVISOR_CONTROL=$SKIP_SUPERVISOR_CONTROL" >&2
        return
    fi

    echo "Stopping supervisor service before provisioning." >&2
    if command -v service >/dev/null 2>&1; then
        if service supervisor stop >/dev/null 2>&1 || ! supervisor_service_is_running; then
            return
        fi
        echo "Failed to stop supervisor service via service." >&2
        exit 1
    fi

    if command -v systemctl >/dev/null 2>&1; then
        if systemctl stop supervisor >/dev/null 2>&1 || ! supervisor_service_is_running; then
            return
        fi
        echo "Failed to stop supervisor service via systemctl." >&2
        exit 1
    fi

    echo "No supported supervisor stop command found." >&2
    exit 1
}

start_supervisor_service() {
    if supervisor_control_is_skipped; then
        echo "Skipping supervisor start because VIDEO_PORTAL_SKIP_SUPERVISOR_CONTROL=$SKIP_SUPERVISOR_CONTROL" >&2
        return
    fi

    echo "Starting supervisor service after provisioning." >&2
    if command -v service >/dev/null 2>&1; then
        service supervisor start >/dev/null 2>&1 || {
            echo "Failed to start supervisor service via service." >&2
            exit 1
        }
    elif command -v systemctl >/dev/null 2>&1; then
        systemctl start supervisor >/dev/null 2>&1 || {
            echo "Failed to start supervisor service via systemctl." >&2
            exit 1
        }
    else
        echo "No supported supervisor start command found." >&2
        exit 1
    fi

    if ! supervisor_service_is_running; then
        echo "Supervisor service is not running after start." >&2
        exit 1
    fi

    supervisorctl reread >/dev/null
    supervisorctl update >/dev/null
}

main() {
    require_root
    require_admin_password
    install_system_packages
    ensure_directories
    stop_supervisor_service
    install_uv
    seed_release_layout
    fix_ownership
    write_shared_env
    ensure_current_env_link
    seed_virtualenv
    install_supervisor_programs
    install_sudoers
    grant_low_port_access
    start_supervisor_service
}

main "$@"
