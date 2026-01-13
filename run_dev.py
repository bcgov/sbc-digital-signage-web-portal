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
    logger.info("="*50)
    logger.info("Video Portal Development Server Starting")
    logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    logger.info("Server running on http://localhost:5000")
    logger.info("="*50)
    
    print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    print("Open browser to: http://localhost:5000")
    
    # Run on port 5000 for development
    app.run(host='127.0.0.1', port=5000, debug=True)
