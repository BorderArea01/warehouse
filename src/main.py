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
import signal
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
    sys.exit(1)

from src.log import get_logger
logger = get_logger("Main")

import torch

# ... (Logging config) ...

class WarehouseSystem:
    def __init__(self):
        self.face_capture: Optional[FaceCapture] = None
        self.time_capture: Optional[TimeCapture] = None
        self.asset_scanning: Optional[AssetScanning] = None
        self._running = False
        self.shared_model = None

    def load_shared_model(self):
        """Load YOLOv5 model once for shared use."""
        logger.info("Loading Shared YOLOv5n Model...")
        try:
            # Load model from torch hub
            self.shared_model = torch.hub.load('ultralytics/yolov5', 'yolov5n', pretrained=True)
            self.shared_model.classes = [0]  # Filter to 'person' class
            logger.info("Shared Model Loaded Successfully.")
        except Exception as e:
            logger.critical(f"Error loading shared model: {e}")
            sys.exit(1)

    def initialize_services(self):
        """Initialize all plugin instances."""
        logger.info("Initializing Warehouse Services...")
        
        # Load model first
        if self.shared_model is None:
            self.load_shared_model()
            
        try:
            # 1. Asset Scanning (RFID)
            self.asset_scanning = AssetScanning()
            
            # 2. Time Capture (Exit Camera)
            # Inject AssetScanning to trigger analysis on exit
            # Inject Shared Model
            self.time_capture = TimeCapture(asset_scanner=self.asset_scanning, model=self.shared_model)
            
            # 3. Face Capture (Entry Camera)
            # Inject Shared Model
            self.face_capture = FaceCapture(model=self.shared_model)
            
            logger.info("All services initialized successfully.")
        except Exception as e:
            logger.critical(f"Service Initialization Failed: {e}")
            sys.exit(1)

    def start(self):
        """Start all background and foreground services."""
        if not self.face_capture or not self.time_capture or not self.asset_scanning:
            self.initialize_services()

        self._running = True
        
        # Setup Signal Handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        print("==========================================")
        print("   Warehouse Monitoring System v1.0")
        print("   - FaceCapture   (Entry & ID)")
        print("   - AssetScanning (RFID Tracking)")
        print("   - TimeCapture   (Exit Monitoring)")
        print("==========================================")

        try:
            # 1. Start Background Services
            logger.info("Starting Background Services...")
            
            logger.info("[1/2] Launching AssetScanning...")
            self.asset_scanning.start_monitoring()
            
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
        # Note: FaceCapture loop might catch KeyboardInterrupt internally,
        # but this ensures we handle SIGTERM or other signals.
        self.stop()

def main():
    system = WarehouseSystem()
    system.start()

if __name__ == "__main__":
    main()
