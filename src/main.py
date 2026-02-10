# -*- coding: utf-8 -*-
"""
Main Entry Point for Warehouse Monitoring System.

This script initializes and coordinates the following services:
1. FaceCapture: Monitors entry, detects faces, identifies users.
2. AssetScanning: Monitors RFID tags, tracks asset movement.
3. TimeCapture: Monitors exit, calculates duration, triggers asset analysis.
"""

import sys
import os
import time
import logging
import logging.handlers
import signal
import threading
import urllib.request
from typing import Optional

# Ensure project root is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

# Import Plugins
try:
    from src.plugins.FaceCapture import FaceCapture
    from src.plugins.TimeCapture import TimeCapture
    from src.plugins.AssetScanning import AssetScanning
except ImportError as e:
    print(f"Critical Error: Failed to import plugins: {e}")
    # We don't exit here immediately to allow for deferred loading if possible, 
    # but practically we need them.
    # However, since we are rewriting them, they might not exist yet if run sequentially.
    pass

# Configure Logging
# Create logs/system directory for main execution logs
log_dir = os.path.join(project_root, 'logs', 'system')
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.TimedRotatingFileHandler(
            os.path.join(log_dir, 'main_run.log'),
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger("Main")

class WarehouseSystem:
    def __init__(self):
        self.face_capture: Optional[FaceCapture] = None
        self.time_capture: Optional[TimeCapture] = None
        self.asset_scanning: Optional[AssetScanning] = None
        self._running = False
        self.model_path = None

    def ensure_model_exists(self):
        """Download MediaPipe EfficientDet model if not present."""
        model_dir = os.path.join(current_dir, 'models')
        os.makedirs(model_dir, exist_ok=True)
        self.model_path = os.path.join(model_dir, 'efficientdet_lite0.tflite')
        
        url = 'https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite'
        
        if not os.path.exists(self.model_path):
            logger.info(f"Downloading MediaPipe model to {self.model_path}...")
            try:
                urllib.request.urlretrieve(url, self.model_path)
                logger.info("Model downloaded successfully.")
            except Exception as e:
                logger.critical(f"Failed to download model: {e}")
                sys.exit(1)
        else:
            logger.info(f"Using existing model at {self.model_path}")

    def initialize_services(self):
        """Initialize all plugin instances."""
        logger.info("Initializing Warehouse Services...")
        
        # Ensure model exists
        self.ensure_model_exists()
            
        try:
            # 1. Asset Scanning (RFID)
            try:
                # Re-import in case it failed earlier or was just created
                from src.plugins.AssetScanning import AssetScanning
                self.asset_scanning = AssetScanning()
            except Exception as e:
                logger.error(f"AssetScanning initialization failed: {e}. Skipping asset tracking.")
                self.asset_scanning = None
            
            # 2. Time Capture (Exit Camera)
            from src.plugins.TimeCapture import TimeCapture
            self.time_capture = TimeCapture(
                asset_scanner=self.asset_scanning, 
                model_path=self.model_path
            )
            
            # 3. Face Capture (Entry Camera)
            from src.plugins.FaceCapture import FaceCapture
            self.face_capture = FaceCapture(
                model_path=self.model_path
            )
            
            logger.info("All services initialized successfully.")
        except Exception as e:
            logger.critical(f"Service Initialization Failed: {e}")
            sys.exit(1)

    def start(self):
        """Start all background and foreground services."""
        if not self.face_capture or not self.time_capture:
            self.initialize_services()

        self._running = True
        
        # Setup Signal Handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        print("==========================================")
        print("   Warehouse Monitoring System v2.0 (MediaPipe)")
        print("   - FaceCapture   (Entry & ID)")
        print("   - AssetScanning (RFID Tracking)")
        print("   - TimeCapture   (Exit Monitoring)")
        print("   - MinioUploader (Image Upload)")
        print("==========================================")

        try:
            # 1. Start Background Services
            logger.info("Starting Background Services...")
            
            if self.asset_scanning:
                logger.info("[1/2] Launching AssetScanning...")
                self.asset_scanning.start_monitoring()
            else:
                logger.info("[1/2] AssetScanning skipped (not initialized).")
            
            logger.info("[2/2] Launching TimeCapture...")
            self.time_capture.start_monitoring()

            # 2. Start Foreground Service (Blocking)
            logger.info("Starting Foreground Service (FaceCapture)...")
            print("Press Ctrl+C to exit.")
            
            # This call blocks until user quits or error occurs
            self.face_capture.start_monitoring()

        except Exception as e:
            logger.error(f"Runtime Error: {e}")
        finally:
            self.stop()

    def stop(self):
        """Stop all services gracefully."""
        if not self._running:
            return
            
        logger.info("Shutting down services...")
        self._running = False

        if self.time_capture:
            self.time_capture.stop_monitoring()
        
        if self.asset_scanning:
            self.asset_scanning.stop_monitoring()
            
        # FaceCapture stops when its loop ends (foreground)
        
        logger.info("System Shutdown Complete.")
        sys.exit(0)

    def _signal_handler(self, sig, frame):
        """Handle system signals (Ctrl+C, etc)."""
        logger.info("Signal received. Initiating shutdown...")
        self.stop()

def main():
    system = WarehouseSystem()
    system.start()

if __name__ == "__main__":
    main()
