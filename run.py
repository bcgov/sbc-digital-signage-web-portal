#!/usr/bin/env python3
from app.routes import app, logger

if __name__ == '__main__':
    # Run on port 80, accessible from all network interfaces
    # Note: Requires sudo or capability to bind to port 80
    logger.info("="*50)
    logger.info("Video Portal Server Starting")
    logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    logger.info("Server running on port 80")
    logger.info("="*50)
    
    app.run(host='0.0.0.0', port=80, debug=False)
