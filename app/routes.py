from flask import render_template, request, jsonify, current_app
import os
import logging
import subprocess
import platform
from datetime import datetime
from logging.handlers import RotatingFileHandler

from . import create_app

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

# Set up file handler with rotation (10MB max, keep 5 backups)
file_handler = RotatingFileHandler('logs/video_portal.log', maxBytes=10485760, backupCount=5)
file_handler.setFormatter(logging.Formatter(
    '[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S %Z'
))
file_handler.setLevel(logging.INFO)

# Get logger
logger = logging.getLogger('video_portal')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)

app = create_app()

@app.route('/')
def index():
    client_ip = request.remote_addr
    logger.info(f"Portal accessed from {client_ip}")
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload():
    client_ip = request.remote_addr
    
    if 'video' not in request.files:
        logger.warning(f"Upload attempt without video file from {client_ip}")
        return jsonify({'error': 'No video file'}), 400
    
    file = request.files['video']
    if file.filename == '':
        logger.warning(f"Upload attempt with empty filename from {client_ip}")
        return jsonify({'error': 'No selected file'}), 400
    
    # Get file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    file_size_mb = file_size / (1024 * 1024)
    
    # Save as SBC-DISPLAY-VIDEO.mp4 (overwrites previous)
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'SBC-DISPLAY-VIDEO.mp4')
    file.save(filepath)
    
    logger.info(f"Video uploaded successfully from {client_ip} | Original: {file.filename} | Size: {file_size_mb:.2f} MB | Saved as: SBC-DISPLAY-VIDEO.mp4")
    
    # Restart video player to pick up the new file (Raspberry Pi only)
    try:
        system = platform.system()
        if system == 'Linux':
            # Restart video looper using supervisorctl
            result = subprocess.run(['sudo', 'supervisorctl', 'restart', 'video_looper'], 
                         capture_output=True, timeout=5, text=True)
            if result.returncode == 0:
                logger.info("Video looper service restarted successfully to load new video")
            else:
                logger.warning(f"Video looper restart returned code {result.returncode}: {result.stderr}")
        else:
            # Simulate on macOS for testing
            logger.info(f"[TEST MODE - {system}] Would execute: sudo supervisorctl restart video_looper")
            logger.info(f"[TEST MODE] Video player reload simulated (skipped on {system})")
    except subprocess.TimeoutExpired:
        logger.warning("Video player restart timed out")
    except Exception as e:
        logger.warning(f"Could not restart video player: {str(e)}")
    
    return jsonify({'success': True, 'message': 'Video uploaded successfully'})

@app.route('/restart', methods=['POST'])
def restart():
    client_ip = request.remote_addr
    logger.warning(f"TV restart requested from {client_ip}")
    
    try:
        # Check if we're on a Raspberry Pi (Linux) or macOS for testing
        system = platform.system()
        
        if system == 'Linux':
            # On Raspberry Pi, execute the reboot command
            logger.info("Executing system reboot...")
            subprocess.Popen(['sudo', 'reboot'])
            return jsonify({'success': True, 'message': 'System restart initiated'})
        else:
            # On macOS or other systems (for testing), just log it
            logger.info(f"Restart requested but skipped (running on {system}, not Raspberry Pi)")
            return jsonify({'success': True, 'message': f'Restart simulated (running on {system})'})
    
    except Exception as e:
        logger.error(f"Restart failed from {client_ip}: {str(e)}")
        return jsonify({'error': 'Restart failed', 'details': str(e)}), 500