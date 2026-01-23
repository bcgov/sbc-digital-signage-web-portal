# Video Upload Portal

A minimal Flask web portal for uploading videos to Raspberry Pi. Users can preview videos before uploading. Uploaded videos are saved as `SBC-DISPLAY-VIDEO.mp4`.

## What It Does

- Displays a web portal with BC Gov branding
- Allows users to select a video file (up to 2GB)
- Shows video preview at 3 seconds
- Uploads confirmed video to `/home/pi/videos/SBC-DISPLAY-VIDEO.mp4`
- Logs all access and uploads with timestamps and IP addresses
- Provides a restart TV button to remotely reboot the Raspberry Pi

## Run Locally (Testing)

```bash
pip3 install -r requirements.txt
python3 run_dev.py
```

Open browser to: http://localhost:5000

## Run on Raspberry Pi

```bash
# Copy files to Pi
scp -r * pi@<raspberry-pi-ip>:/home/pi/video-portal

# SSH to Pi and run
ssh pi@<raspberry-pi-ip>
cd /home/pi/video-portal
pip3 install -r requirements.txt
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python3.7
python3 run.py
```

Portal runs on port 80. Access from any device on the network: `http://<raspberry-pi-ip>`

See [DEPLOY.md](DEPLOY.md) for auto-start on boot setup.

## Restart TV Feature

The portal includes a "Restart TV" button that allows remote rebooting of the Raspberry Pi.

**How to Use:**
1. Click the "🔄 Restart TV" button in the web portal
2. Confirm the restart action in the dialog that appears
3. The Raspberry Pi will reboot immediately
4. The portal will be unavailable for approximately 1-2 minutes while the system restarts
5. After reboot, the portal will be accessible again automatically

**Notes:**
- The restart requires sudo privileges configured for the `pi` user
- All restart attempts are logged with IP addresses for security
- On non-Raspberry Pi systems (e.g., macOS), the restart command is simulated for testing purposes

## Logs

All activity logged to `logs/video_portal.log`
