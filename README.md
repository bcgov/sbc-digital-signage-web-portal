# Video Upload Portal

A minimal Flask web portal for uploading videos to Raspberry Pi. Users can preview videos before uploading. Uploaded videos are saved as `SBC-DISPLAY-VIDEO.mp4`.

## What It Does

- Displays a web portal with BC Gov branding
- Allows users to select a video file (up to 2GB)
- Shows video preview at 3 seconds
- Uploads confirmed video to `/home/pi/videos/SBC-DISPLAY-VIDEO.mp4`
- Logs all access and uploads with timestamps and IP addresses

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
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python3
python3 run.py
```

Portal runs on port 80. Access from any device on the network: `http://<raspberry-pi-ip>`

See [DEPLOY.md](DEPLOY.md) for auto-start on boot setup.

## Logs

All activity logged to `logs/video_portal.log`
