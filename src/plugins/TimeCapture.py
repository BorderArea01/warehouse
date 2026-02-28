# -*- coding: utf-8 -*-
"""
Time Capture Plugin for Warehouse Monitoring System (MediaPipe Version).

This module:
1. Monitors the warehouse exit camera (RTSP stream).
2. Detects when the warehouse becomes empty (exit event) using MediaPipe.
3. Updates visit records with end times.
4. Triggers asset analysis via the AssetScanning plugin.
5. Reports complete visit events to the central agent.
"""

import cv2
import time
import os
import sys
import threading
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

# MediaPipe Imports
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Local Imports
from src.config import Config
try:
    from src.plugins.ToAgent import ToAgent
except ImportError:
    # Fallback for circular imports or testing if needed
    ToAgent = None

# Configure logger
logger = logging.getLogger("TimeCapture")

# ================= Time Capture Service =================

class TimeCapture:
    """
    Service for monitoring exit events and updating visit records.
    """

    def __init__(self, asset_scanner=None, model_path=None):
        self.rtsp_url = Config.RTSP_URL_TIMECAPTURE
        self.bj_tz = timezone(timedelta(hours=8))
        self.to_agent = ToAgent(module_name="TimeCapture") if ToAgent else None
        self.asset_scanner = asset_scanner
        self.model_path = model_path
        
        self.confidence_threshold = Config.TIME_CONFIDENCE_THRESHOLD
        self.person_timeout = Config.TIME_PERSON_TIMEOUT
        
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.detector = None

    def get_bj_time(self) -> datetime:
        """Get current time in Beijing Timezone."""
        return datetime.now(self.bj_tz)

    def _init_detector(self):
        """Initialize MediaPipe Object Detector."""
        if self.detector:
            return

        logger.info(f"Loading MediaPipe model from {self.model_path}...")
        try:
            base_options = python.BaseOptions(model_asset_path=self.model_path)
            options = vision.ObjectDetectorOptions(
                base_options=base_options,
                score_threshold=self.confidence_threshold,
                max_results=5,
                category_allowlist=["person"]
            )
            self.detector = vision.ObjectDetector.create_from_options(options)
            logger.info("MediaPipe Object Detector loaded successfully.")
        except Exception as e:
            logger.critical(f"Failed to load MediaPipe model: {e}")
            sys.exit(1)

    def start_monitoring(self):
        """Start the background monitoring thread."""
        if self.running:
            logger.warning("Monitoring already running.")
            return

        self._init_detector()

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("TimeCapture Monitoring started.")

    def stop_monitoring(self):
        """Stop the monitoring thread."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        logger.info("TimeCapture Monitoring stopped.")

    def _monitor_loop(self):
        """Main loop to read RTSP stream and detect person presence."""
        cap = cv2.VideoCapture(self.rtsp_url)
        if not cap.isOpened():
            logger.error(f"Could not open RTSP stream: {self.rtsp_url}")
            self.running = False
            return

        logger.info("Connected to Camera. Listening for exit events...")

        # Optimization: Skip frames
        frame_count = 0
        skip_frames = 5
        
        # State
        last_seen_time = time.time()
        is_session_active = False  # Are we currently tracking a visit?

        while self.running:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Stream disconnected. Reconnecting in 5s...")
                time.sleep(5)
                cap = cv2.VideoCapture(self.rtsp_url)
                continue

            frame_count += 1
            if frame_count % skip_frames != 0:
                continue

            # MediaPipe Inference
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                
                detection_result = self.detector.detect(mp_image)
                
                # Check for person
                seen_now = False
                for detection in detection_result.detections:
                    if detection.categories[0].score >= self.confidence_threshold:
                        seen_now = True
                        break
            except Exception as e:
                logger.error(f"Inference Error: {e}")
                seen_now = False

            current_time = time.time()
            
            if seen_now:
                last_seen_time = current_time
                if not is_session_active:
                    # New person arrived (or re-entered)
                    is_session_active = True
                    logger.info("Person Detected in Warehouse. Tracking session...")
            
            else:
                if is_session_active:
                    # Person was here, now gone. Check timeout.
                    duration_gone = current_time - last_seen_time
                    if duration_gone > self.person_timeout:
                        # TIMEOUT REACHED -> EVENT END
                        end_time = self.get_bj_time()
                        logger.info(f"Person Left Warehouse (Timeout {self.person_timeout}s).")
                        
                        # Trigger Agent to update DB
                        self.report_exit_event(end_time)
                        
                        is_session_active = False

            # Optional: Sleep to save CPU
            time.sleep(0.1)

        cap.release()

    def report_exit_event(self, end_time: datetime):
        """
        Handle exit event: update local logs, trigger asset analysis, and report to agent.
        """
        end_time_str = end_time.strftime("%Y-%m-%d_%H:%M:%S")
        
        # 1. Update Local File and Get Full Records
        closed_records = self._update_local_json_end_time(end_time_str)
        
        if not closed_records:
            logger.info("No open records found to close.")
            return

        for record in closed_records:
            # We now send the COMPLETE record
            start_t = record.get('start_time')
            end_t = record.get('end_time')
            
            # --- Trigger Asset Analysis and Wait for Result ---
            asset_changes = []
            if self.asset_scanner:
                try:
                    asset_changes = self.asset_scanner.get_asset_changes(start_t, end_t)
                except Exception as e:
                    logger.error(f"Error getting asset changes: {e}")
            
            record['asset_changes'] = asset_changes
            # ------------------------------

            self._send_record_to_agent(record)

    def _send_record_to_agent(self, record: Dict[str, Any]):
        """Format and send the complete record to the Agent."""
        if not self.to_agent:
            logger.warning("Agent not available. Skipping upload.")
            return

        end_t = record.get('end_time')
        # Format times
        end_str = end_t
        try:
             if 'T' in str(end_str):
                 e_dt = datetime.fromisoformat(end_str)
                 end_str = e_dt.strftime("%Y-%m-%d_%H:%M:%S")
        except Exception:
            pass
        
        query = (
            f"检测到人员已经离开：\n"
            f"时间：{end_str}；\n"
            f"区域：小仓库；\n"
            f"资产变动情况：{json.dumps(record.get('asset_changes', []), ensure_ascii=False)}"
        )
        
        try:
            self.to_agent.invoke(query=query)
        except Exception as e:
            logger.error(f"Error invoking Agent: {e}")

    def _update_local_json_end_time(self, end_time_str: str) -> List[Dict[str, Any]]:
        """
        Scans the daily JSONL file for open records and updates them.
        Returns a list of the records that were just closed.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        log_dir = os.path.join(Config.PROJECT_ROOT, 'logs', 'person')
        json_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")

        if not os.path.exists(json_path):
            logger.warning("Today's JSONL file not found.")
            return []

        closed_records_list = []

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if not lines:
                return []

            updated_count = 0
            
            for i, line in enumerate(lines):
                try:
                    record = json.loads(line)
                    # Check if incomplete
                    if record.get('event_type') != 'completed_visit':
                        # Update this record
                        record['end_time'] = end_time_str
                        
                        start_time_val = record['start_time']
                        try:
                            if 'T' in start_time_val:
                                start_dt = datetime.fromisoformat(start_time_val)
                            else:
                                start_dt = datetime.strptime(start_time_val, "%Y-%m-%d_%H:%M:%S")
                                
                            if 'T' in end_time_str:
                                end_dt = datetime.fromisoformat(end_time_str)
                            else:
                                end_dt = datetime.strptime(end_time_str, "%Y-%m-%d_%H:%M:%S")
                                
                            record['duration_seconds'] = (end_dt - start_dt).total_seconds()
                        except Exception:
                            record['duration_seconds'] = 0
                            
                        record['event_type'] = "completed_visit"
                        
                        closed_records_list.append(record)
                        lines[i] = json.dumps(record, ensure_ascii=False) + "\n"
                        updated_count += 1
                except:
                    continue
            
            if updated_count > 0:
                with open(json_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                logger.info(f"Closed {updated_count} open records.")
                
            return closed_records_list
                
        except Exception as e:
            logger.error(f"Error updating local JSON: {e}")
            return []
