#!/usr/bin/env python3
"""
Development server for local testing on Mac/Linux/Windows
Runs on port 5000 instead of 80 (no sudo required)
"""
import os

# Set upload folder BEFORE importing app
os.environ['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')

from app.routes import app, logger

if __name__ == '__main__':
    # Enable debug mode via environment variable (defaults to False for security)
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes')
    
    logger.info("="*50)
    logger.info("Video Portal Development Server Starting")
    logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    logger.info("Server running on http://localhost:5000")
    logger.info(f"Debug mode: {debug_mode}")
    logger.info("="*50)
    
    print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    print("Open browser to: http://localhost:5000")
    print(f"Debug mode: {debug_mode} (Set FLASK_DEBUG=true to enable)")
    
    # Run on port 5000 for development
    app.run(host='127.0.0.1', port=5000, debug=debug_mode)
