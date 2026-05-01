#!/usr/bin/env python3
from app import create_app, get_app_config

app = create_app()

if __name__ == "__main__":
    config = get_app_config()
    server_url = f"http://{config['HOST']}:{config['PORT']}"
    logger = app.logger

    logger.info("=" * 50)
    logger.info("Video Portal Server Starting")
    logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    logger.info(f"Server running on {server_url}")
    logger.info(f"Debug mode: {config['DEBUG']}")
    logger.info(f"Portal root: {app.config['PORTAL_ROOT']}")
    logger.info(f"App version: {app.config['APP_VERSION']}")
    logger.info("=" * 50)

    print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    print(f"Open browser to: {server_url}")
    print(f"Debug mode: {config['DEBUG']}")

    app.run(
        host=config["HOST"],
        port=config["PORT"],
        debug=config["DEBUG"],
    )
