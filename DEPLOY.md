# Raspberry Pi Deployment

## Prerequisites
- Raspberry Pi 3 with Raspberry Pi OS
- Network connection

## Quick Setup

### 1. Copy files to Pi
```bash
scp -r * pi@<raspberry-pi-ip>:/home/pi/video-portal
```

### 2. SSH and install
```bash
ssh pi@<raspberry-pi-ip>
cd /home/pi/video-portal
sudo apt update && sudo apt install python3 python3-pip -y
pip3 install -r requirements.txt
mkdir -p /home/pi/videos
```

### 3. Allow port 80 access
```bash
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python3.7
```
### 4. Configure Restart TV Button
Allow the portal to restart the Pi without password:
```bash
sudo visudo
```
Add this line at the bottom:
```
pi ALL=(ALL) NOPASSWD: /sbin/reboot
```
Save and exit (Ctrl+X, Y, Enter).

### 5. Test
```bash
python3 run.py
```

Access portal at: `http://<raspberry-pi-ip>`

Press `Ctrl+C` to stop.

## Auto-Start on Boot

Create systemd service:
```bash
sudo nano /etc/systemd/system/video-portal.service
```

Paste this:
```ini
[Unit]
Description=Video Upload Portal
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/video-portal
ExecStart=/usr/bin/python3 /home/pi/video-portal/run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable video-portal
sudo systemctl start video-portal
sudo systemctl status video-portal
```

## Firewall (Optional)

```bash
sudo apt install ufw -y
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw allow 22/tcp
sudo ufw enable
```

## Troubleshooting

**View logs:**
```bash
# Application logs
tail -f /home/pi/video-portal/logs/video_portal.log

# System logs
sudo journalctl -u video-portal -f
```

**Restart service:**
```bash
sudo systemctl restart video-portal
```

**Stop service:**
```bash
sudo systemctl stop video-portal
```

**Run manually for testing:**
```bash
cd /home/pi/video-portal
python3 run.py
```

## Configuration

- **Upload location**: `/home/pi/videos/SBC-DISPLAY-VIDEO.mp4`
- **Max file size**: 2GB
- **Port**: 80
- **Logs**: `logs/video_portal.log` (auto-rotates at 10MB)
