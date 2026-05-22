# Video Upload Portal for Raspberry Pi

This repository provisions and runs a Flask-based upload portal for Raspberry Pi signage devices. The deployed system supports:

- video uploads to `/home/pi/videos/SBC-DISPLAY-VIDEO.mp4`
- remote restart of the video looper after uploads
- remote reboot through the portal UI
- offline-safe full-project updates with rollback
- a Docker harness for disposable testing

## Set Up the Pi Base Image

These steps prepare the Adafruit `pi_video_looper` image before the portal is installed. The portal provisioning script assumes everything in this section is already complete.

### Download and burn the image

The base image can be downloaded from [videolooper.de](https://videolooper.de).

Write the image to the SD card with a raw image writer such as HDD Raw Copy, then boot the Pi.

### Connect the Pi to the network

```bash
sudo raspi-config
reboot
```

Use `raspi-config` to join Wi-Fi or configure Ethernet, and set the correct country in localization settings.

### Point APT at the Debian Buster archive

Replace `/etc/apt/sources.list` with:

```text
deb http://archive.debian.org/debian buster main contrib non-free
deb http://archive.debian.org/debian-security buster/updates main contrib non-free
```

Create `/etc/apt/apt.conf.d/99buster-eol` with:

```text
Acquire::Check-Valid-Until "false";
Acquire::AllowInsecureRepositories "true";
Acquire::AllowDowngradeToInsecureRepositories "true";
APT::Get::AllowUnauthenticated "true";
```

Remove stale metadata and install the base customization packages:

```bash
sudo rm -rf /var/lib/apt/lists/*
sudo apt update
sudo apt upgrade -y --allow-unauthenticated
sudo apt install -y network-manager --allow-unauthenticated
sudo apt install -y ufw --allow-unauthenticated
```

### Configure the video looper

Edit `/boot/video_looper.ini` and set:

```ini
file_reader = directory
path = /home/pi/videos
```

### Configure locale and keyboard

```bash
sudo locale-gen en_CA.UTF-8
sudo raspi-config nonint do_change_locale en_CA.UTF-8
sudo raspi-config nonint do_configure_keyboard us
reboot
```

### Configure hotspot mode

Disconnect Wi-Fi, disable `dhcpcd`, and let NetworkManager manage `wlan0`:

```bash
nmcli device disconnect wlan0
sudo systemctl disable dhcpcd
sudo systemctl stop dhcpcd
sudo systemctl mask dhcpcd
sudo systemctl enable NetworkManager
sudo systemctl start NetworkManager
```

Update `/etc/NetworkManager/NetworkManager.conf` so `managed=true`, then create the hotspot:

```bash
nmcli connection add type wifi ifname wlan0 con-name hotspot autoconnect yes ssid Pi-Hotspot
nmcli connection modify hotspot \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  ipv4.method shared \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk StrongPassword123
nmcli connection up hotspot
```

### Restrict network access

Allow only the portal on port 80:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw enable
```

Disable Ethernet at boot:

```bash
sudo tee /usr/local/bin/force-disable-eth0.sh >/dev/null <<'EOF'
/usr/sbin/ip link set eth0 down
EOF
sudo chmod +x /usr/local/bin/force-disable-eth0.sh
```

Create `/etc/systemd/system/force-disable-eth0.service`:

```ini
[Unit]
Description=Force eth0 down
After=network.target

[Service]
ExecStart=/usr/local/bin/force-disable-eth0.sh
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

Enable the service and disable SSH:

```bash
sudo systemctl daemon-reload
sudo systemctl enable force-disable-eth0.service
sudo systemctl start force-disable-eth0.service
sudo systemctl disable ssh
sudo systemctl stop ssh
```

## Provision the Video Upload Portal

### Deploy from a fresh clone

The supported provisioning flow is always:

1. Clone the repository into `/home/pi/video-portal`.
2. SSH into the device.
3. Run the shared provisioning script as root.

```bash
git clone <repo-url> /home/pi/video-portal
ssh pi@<raspberry-pi-ip>
cd /home/pi/video-portal
sudo ./scripts/provision.sh
```

The script installs the required OS packages, stops Supervisor before mutating the live runtime, installs `uv` into the portal user home and symlinks it into `/usr/local/bin/uv`, installs Python `3.14.4` into `/home/pi/video-portal/.uv/python`, migrates the app into the release layout, hands the runtime tree to the portal user, writes the deployed `.env`, creates the `current/app/.env` symlink, creates `current/.venv` with `uv sync` as the portal user, installs Supervisor programs, installs sudoers permissions, grants Python permission to bind port 80, and then starts Supervisor again.

If you need to reprovision a device, delete `/home/pi/video-portal`, clone the repo again, and rerun `sudo ./scripts/provision.sh`. Re-running the script against an already migrated checkout is not the supported recovery path.

### Deployed configuration

The provisioner creates `/home/pi/video-portal/shared/app/.env` with:

```dotenv
FLASK_HOST=0.0.0.0
FLASK_PORT=80
FLASK_DEBUG=false
UPLOAD_FOLDER=/home/pi/videos
MAX_CONTENT_LENGTH=2147483648
VIDEO_PORTAL_ADMIN_USERNAME=admin
VIDEO_PORTAL_ADMIN_PASSWORD=admin
```

On deployed systems, this `shared/app/.env` file is the persistent runtime configuration source and is written as the portal user.

### Verify the deployment

```bash
sudo supervisorctl status video-portal
sudo supervisorctl status video-portal-update
curl http://127.0.0.1/healthz
```

Access the portal from another device at `http://<raspberry-pi-ip>`.

On Debian Buster-based Raspberry Pi images, `supervisord` itself may still run under Python 2.7. That is expected and separate from the portal runtime, which is launched from `current/.venv/bin/python`.

## Runtime Layout

After provisioning, the Pi uses this layout:

```text
/home/pi/video-portal/
  current -> releases/<release-id>
  deploy -> current/deploy
  logs/
  releases/
  releases_failed/
  shared/
    app/.env
  scripts -> current/scripts
  tools -> current/tools
  updates/
    incoming/
    logs/
    staging/
  updater/
    state.json            persistent updater state
    update.lock
```

Each release contains:

```text
releases/<release-id>/
  .python-version
  .venv/
  app/
    main.py
    app/
  deploy/
  main.py
  pyproject.toml
  scripts/
    postdeploy/
    predeploy/
  tools/
  updater/
  VERSION
  manifest.json          update releases only
  uv-cache/              update releases only
  uv.lock
```

The main portal and updater both run from `current`, while persistent device-specific files and updater state live outside the release under `shared/` and the portal-root `updater/` directory.

## Day-to-Day Operation

### Uploads and video reload

- The portal stores uploads at `/home/pi/videos/SBC-DISPLAY-VIDEO.mp4`.
- After a successful upload, the app restarts `video_looper` with Supervisor so the new video starts playing.

### Restart TV button

- The portal’s restart button runs `sudo reboot`.
- `scripts/provision.sh` installs the required sudoers rules, so no manual `visudo` step is needed.

### Logs and health checks

Useful locations and commands:

```bash
curl http://127.0.0.1/healthz
curl http://127.0.0.1/status
tail -f /home/pi/video-portal/logs/video_portal.log
sudo supervisorctl tail -f video-portal
sudo supervisorctl tail -f video-portal-update
```

## Offline Update System

The updater never overwrites the live app in place. Every uploaded package is staged, verified, installed into a new release, switched atomically, health-checked, and rolled back automatically if anything fails.

When the updater installs a release, it resolves `uv` in this order:

1. `VIDEO_PORTAL_UV_BIN`, if set
2. `/usr/local/bin/uv`, if it exists and is executable by the updater user
3. `~/.local/bin/uv` for the updater user
4. `uv` from the updater process `PATH`

`VIDEO_PORTAL_UV_BIN` is the explicit override if your device uses a different install location. The default provisioned path is `/usr/local/bin/uv`, which should symlink to the portal user's install under `~/.local/bin/uv`. Provisioning installs managed Python into `/home/pi/video-portal/.uv/python`, and update-time `uv sync` requires uv-managed Python from that location instead of falling back to system Python on `PATH`. If `/usr/local/bin/uv` exists but the updater user cannot access or execute it, the updater skips it and falls back to a user-executable `uv` instead.

### Supervisor programs

Provisioning installs these Supervisor definitions:

```ini
[program:video-portal]
command=/home/pi/video-portal/current/.venv/bin/python /home/pi/video-portal/current/app/main.py
directory=/home/pi/video-portal/current
autostart=true
autorestart=true

[program:video-portal-update]
command=python3 /home/pi/video-portal/current/updater/updater.py
directory=/home/pi/video-portal/current
autostart=false
autorestart=false
```

### Build an update package

The builder packages a local source tree. It reads the package version from `VERSION` and the Python version from `.python-version` in that tree. Build packages from a normal source checkout on a Linux environment that matches the Raspberry Pi target as closely as possible and has `uv` available.

Prepare the checkout first:

```bash
uv sync
```

Build from the local source tree:

```bash
./.venv/bin/python tools/build_release.py
```

`uv run python tools/build_release.py ...` is equivalent if you prefer `uv run`.

The default healthcheck URL is `http://127.0.0.1:80/healthz`. Override the healthcheck URL only when needed:

```bash
./.venv/bin/python tools/build_release.py \
  --healthcheck-url http://127.0.0.1:5000/healthz
```

The output file is written to `dist/video-portal-update-<version>.zip`.

Update packages contain the full managed project snapshot for a release: the app runtime tree, updater code, tools, deploy scripts, deploy assets, root project metadata, `VERSION`, `manifest.json`, and the offline `uv-cache/`.

#### Build on a provisioned Raspberry Pi

Do not run `tools/build_release.py` directly from the provisioned `/home/pi/video-portal` deployment tree.

After provisioning, `/home/pi/video-portal` is a release-layout install: the active runtime lives under `current/`, the checkout-level `.venv` is gone, and the source checkout has been transformed into release directories plus convenience symlinks.

If you want to build an update package on the device itself, create a separate source checkout and build from there:

```bash
git clone <repo-url> ~/video-portal-build
cd ~/video-portal-build
uv sync
./.venv/bin/python tools/build_release.py
```

### Upload flow

1. Open `http://<raspberry-pi-ip>/admin`.
2. Upload the update `.zip`.
3. The app stores it in `updates/incoming/`.
4. The app starts `video-portal-update` with Supervisor.
5. The updater stages the package, verifies hashes, creates a new release, applies the shared overlay, and runs offline `uv sync` from the bundled `uv-cache/`.
6. The updater runs new `scripts/predeploy/*.sh` migrations in version order.
7. The updater switches `current`, restarts services, and checks `/healthz`.
8. The updater runs new `scripts/postdeploy/*.sh` migrations in version order and checks `/healthz` again.
9. If the new release fails after the switch, the updater rolls back to `last_known_good`.

The `Console` tab opens a browser-based terminal session to the device shell for authenticated administrators.

### Deploy migrations

Deploy migrations live inside the release package under:

```text
scripts/predeploy/
scripts/postdeploy/
```

Rules and behavior:

- Hook files must be named `<digits>_<slug>.sh`, for example `0007_update_boot_config.sh` or `20260430123000_install_supervisor_conf.sh`.
- The updater sorts migration filenames lexically and only runs scripts newer than the last successful migration recorded for that phase.
- Previously applied migration numbers are treated as immutable. If you need to change behavior, add a new higher-numbered script instead of editing an older one and expecting it to rerun.
- `predeploy` runs after the new release has been created and dependencies installed, but before `current` is switched.
- `postdeploy` runs only after the new release has been switched live, restarted, and passed an initial health check.
- The updater records `last_successful_predeploy_migration` and `last_successful_postdeploy_migration` in `/home/pi/video-portal/updater/state.json`.
- Predeploy migrations are monotonic. If a later step fails and the app rolls back, already recorded successful migrations are not automatically undone.

Hook environment variables:

- `VIDEO_PORTAL_RELEASE_DIR`
- `VIDEO_PORTAL_PORTAL_ROOT`
- `VIDEO_PORTAL_VERSION`
- `VIDEO_PORTAL_PHASE`
- `VIDEO_PORTAL_PREVIOUS_RELEASE`
- `VIDEO_PORTAL_MIGRATION_VERSION`

Example use cases:

- install updated Supervisor config files from `deploy/supervisor/` into `/etc/supervisor/conf.d/`
- update `/boot/config.txt`
- copy versioned sudoers content from `deploy/sudoers/`

### Hook privileges

Hook scripts run as the `pi` user. Provisioning installs passwordless `sudo` for `pi`, so a predeploy or postdeploy script may elevate explicitly when it needs to modify system files.

That model is intended for offline device management from repo-controlled release packages. For example:

```bash
sudo install -m 644 \
  "$VIDEO_PORTAL_RELEASE_DIR/deploy/supervisor/video-portal-update.conf" \
  /etc/supervisor/conf.d/video-portal-update.conf
sudo supervisorctl reread
sudo supervisorctl update
```

### Manual verification

```bash
curl http://127.0.0.1/healthz
curl http://127.0.0.1/status
ls -1 /home/pi/video-portal/updates/logs
ls -1 /home/pi/video-portal/releases_failed
```

A good end-to-end verification sequence is:

1. Confirm the baseline service is healthy.
2. Upload a valid package and confirm `/healthz` returns the new version.
3. Confirm the new release contains the expected `updater/`, `tools/`, `scripts/`, and `deploy/` content under `current/`.
4. Upload a package with a failing postdeploy migration and confirm the updater rolls back automatically.
5. Confirm `/status` reports the last error, `last_known_good`, and the latest successful migration markers.

## Docker Test Harness

The Docker image uses the same `scripts/provision.sh` flow as the Raspberry Pi deployment. Docker-specific behavior stays in the `Dockerfile` and the `docker/` helper files.
During `docker build`, the image sets `VIDEO_PORTAL_SKIP_SUPERVISOR_CONTROL=true` so provisioning installs the Supervisor config without trying to stop or start a daemon before container runtime.

Build the image:

```bash
docker build -t video-portal .
```

Run the container and publish the portal on host port 5000:

```bash
docker run --rm -p 5000:80 --name video-portal video-portal
```

Then verify:

```bash
curl http://127.0.0.1:5000/healthz
```

The container already provisions the app during `docker build`, so container startup only launches `supervisord`. Treat it as a runtime verification environment, not a package-build checkout. To build update packages, use a separate repo checkout with `uv sync` and run `uv run python tools/build_release.py ...` from that checkout.

## Local Development

For simple local testing outside Docker:

```bash
uv python install 3.14.4
uv sync
cp .env.example .env
uv run main.py
```

By default the development `.env` binds to `127.0.0.1:5000`.

## Troubleshooting

### Common checks

```bash
sudo supervisorctl status
sudo supervisorctl restart video-portal
sudo supervisorctl restart video-portal-update
tail -f /home/pi/video-portal/logs/video_portal.log
```

### If provisioning fails

- Delete `/home/pi/video-portal`, clone again, and rerun `sudo ./scripts/provision.sh`.
