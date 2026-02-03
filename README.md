# Setting up the Pi

The Pi uses pi_video_looper by adafruit(https://github.com/adafruit/pi_video_looper) as the image. It's then tweaked for our usage.
The "pi_video_looper" image uses buster ,based on Debian 10  as base image.


##Download the image

The latest images can be obtained from the following url:

https://videolooper.de


##Burn the image to the sd card

Use a raw image copier like "HDDRAWCopy" to write the files to a sd card and then insert it into the pi


##Download additional packages

We use network-manager and ufw for customizing the images and hence will need to download additional packages after acoonecting to internet

###Connec to a wifi/ethernet

$sudo raspi-config >> enter the wifi name/password and address also change country in local settings

```bash
#reboot
```

###Since debian 10 has reached eol , we need the following tweaks


####replace everything in sources file with the following:

```bash
sudo nano /etc/apt/sources.list
```


deb http://archive.debian.org/debian buster main contrib non-free
deb http://archive.debian.org/debian-security buster/updates main contrib non-free

####create this file

```bash
sudo nano /etc/apt/apt.conf.d/99no-check-valid-until
```

add:

Acquire::Check-Valid-Until "false";


####create 99buster-eol file

```bash
sudo nano /etc/apt/apt.conf.d/99buster-eol
```


add:

Acquire::Check-Valid-Until "false";
Acquire::AllowInsecureRepositories "true";
Acquire::AllowDowngradeToInsecureRepositories "true";

#### Remove stale release metadata

```bash
sudo rm -rf /var/lib/apt/lists/*
```


###Install the packages:

```bash
$sudo apt update
$sudo apt upgrade -y
$sudo apt install -y network-manager --allow-unauthenticated
$sudo apt install -y ufw --allow-unauthenticated
```

##Videop Looper settings

Video_looper settings can be changed by editing /boot/videolooper.ini

There are 2 config changes that we do in this file:


file_reader = directory   -- >> change to directory so that it plays from internal sd card
path = /home/pi/videos   -- >> path from where it plays the video files

##Setting Locales

###To generate locale if not present
```bash
sudo locale-gen en_CA.UTF-8
sudo locale-gen en_CA.UTF-8
```

### change the locales using either raspi-config gui or command line.

```bash
# Locale
sudo raspi-config nonint do_change_locale en_CA.UTF-8
# Keyboard layout
sudo raspi-config nonint do_configure_keyboard us
```

Reboot




##Setting up Hotspot

###disconnect the wifi

```bash
nmcli device disconnect wlan0
```

###disable dhcp and enable network manager

```bash
sudo systemctl disable dhcpcd
sudo systemctl stop dhcpcd
sudo systemctl mask dhcpcd
sudo systemctl enable NetworkManager
sudo systemctl start NetworkManager
```

###Tell NetworkManager to manage wlan0

```bash
sudo nano /etc/NetworkManager/NetworkManager.conf
```

change manages to yes


```bash
nmcli general status
```
```bash
nmcli connection add type wifi ifname wlan0 con-name hotspot autoconnect yes ssid Pi-Hotspot(name of hotspot)

nmcli connection modify hotspot \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  ipv4.method shared \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk StrongPassword123

nmcli connection up hotspot
```


##Block all ports and ehternet


###Block ports

```bash
sudo apt install ufw -y
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw enable
```

###Disable ethernet


####create a script to disabel ethernet

```bash
sudo nano /usr/local/bin/force-disable-eth0.sh
```

```bash
/usr/sbin/ip link set eth0 down
```

####Make it executable

```bash
sudo chmod +x /usr/local/bin/force-disable-eth0.sh
```


####Run the script at boot via systemd

```bash
sudo nano /etc/systemd/system/force-disable-eth0.service
```

add these lines

```bash
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

####Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable force-disable-eth0.service
sudo systemctl start force-disable-eth0.service
```

###Disable SSH

```bash
sudo systemctl disable ssh
sudo systemctl stop ssh
```



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
