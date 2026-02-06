# -*- coding: utf-8 -*-
"""
Time Capture Plugin for Warehouse Monitoring System.

This module:
1. Monitors the warehouse exit camera (RTSP stream).
2. Detects when the warehouse becomes empty (exit event).
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
import torch
import warnings
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

# Suppress PyTorch warnings
warnings.filterwarnings("ignore", category=FutureWarning)

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

from src.log import get_logger
logger = get_logger("TimeCapture")

# Try importing ToAgent
try:
    from src.plugins.ToAgent import ToAgent
except ImportError:
    sys.path.append(os.path.join(project_root, 'src', 'plugins'))
    try:
        from ToAgent import ToAgent
    except ImportError:
        logger.warning("Could not import ToAgent. Server reporting will be disabled.")
        ToAgent = None

# ================= Configuration Constants =================

RTSP_URL = "rtsp://admin:Lzwc%402025.@192.168.13.140:554/Streaming/Channels/101"
CONFIDENCE_THRESHOLD = 0.5
PERSON_TIMEOUT = 5.0  # Seconds of no person seen to consider "Left"

# ================= Time Capture Service =================

class TimeCapture:
    """
    Service for monitoring exit events and updating visit records.
    """

    def __init__(self, asset_scanner=None, model=None):
        """
        Initialize the TimeCapture service.
        
        Args:
            asset_scanner: Optional instance of AssetScanning plugin for triggering analysis.
            model: Optional shared YOLOv5 model.
        """
        self.rtsp_url = RTSP_URL
        self.bj_tz = timezone(timedelta(hours=8))
        self.to_agent = ToAgent() if ToAgent else None
        self.asset_scanner = asset_scanner
        
        self.json_path = os.path.join(project_root, 'visit_records.jsonl')
        
        self.confidence_threshold = CONFIDENCE_THRESHOLD
        self.person_timeout = PERSON_TIMEOUT
        
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.model = model

    def get_bj_time(self) -> datetime:
        """Get current time in Beijing Timezone."""
        return datetime.now(self.bj_tz)

    def load_model(self):
        """Load YOLOv5n model from Torch Hub."""
        if self.model is not None:
            return

        logger.info("Loading YOLOv5n model...")
        try:
            self.model = torch.hub.load('ultralytics/yolov5', 'yolov5n', pretrained=True)
            self.model.classes = [0]  # Filter to 'person' class
        except Exception as e:
            logger.error(f"Error loading model: {e}")

    def start_monitoring(self):
        """Start the background monitoring thread."""
        if self.running:
            logger.warning("Monitoring already running.")
            return

        if self.model is None:
            self.load_model()

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

            # Inference
            results = self.model(frame)
            detections = results.xyxy[0].cpu().numpy()
            
            # Check for person
            seen_now = False
            for *xyxy, conf, cls in detections:
                if conf >= self.confidence_threshold and int(cls) == 0:
                    seen_now = True
                    break
            
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
        end_time_str = end_time.isoformat()
        
        # 1. Update Local File and Get Full Records
        closed_records = self._update_local_json_end_time(end_time_str)
        
        if not closed_records:
            logger.info("No open records found to close.")
            return

        for record in closed_records:
            # We now send the COMPLETE record
            start_t = record.get('start_time')
            end_t = record.get('end_time')
            
            # --- Trigger Asset Analysis ---
            if self.asset_scanner:
                self._trigger_asset_analysis(start_t, end_t)
            # ------------------------------

            self._send_record_to_agent(record)

    def _trigger_asset_analysis(self, start_t, end_t):
        """Run asset analysis in a separate thread."""
        try:
            threading.Thread(
                target=self.asset_scanner.analyze_asset_changes,
                args=(start_t, end_t),
                daemon=True
            ).start()
        except Exception as e:
            logger.error(f"Error triggering Asset Analysis: {e}")

    def _send_record_to_agent(self, record: Dict[str, Any]):
        """Format and send the complete record to the Agent."""
        if not self.to_agent:
            logger.warning("Agent not available. Skipping upload.")
            return

        start_t = record.get('start_time')
        end_t = record.get('end_time')
        face_res = record.get('face_result', {})
        yolo_conf = record.get('yolo_confidence', 0.95)
        
        # Format times
        try:
            s_dt = datetime.fromisoformat(start_t)
            e_dt = datetime.fromisoformat(end_t)
            
            start_str = f"{s_dt.hour}点{s_dt.minute:02d}分"
            if e_dt.minute == 0:
                 end_str = f"{e_dt.hour}点"
            else:
                 end_str = f"{e_dt.hour}点{e_dt.minute:02d}分"
                 
        except Exception as e:
            logger.error(f"Time formatting error: {e}")
            start_str = start_t
            end_str = end_t
        
        # Extract Identity Info
        user_id = "Unknown"
        nick_name = "Unknown"
        
        if isinstance(face_res, dict) and face_res.get("code") == 200:
             data = face_res.get("data", {})
             user_id = data.get("userId", "Unknown")
             nick_name = data.get("nickName", "Unknown")
    
        query = (
            f"记录人员进出流水：开始时间 {start_str}，结束时间 {end_str} ，"
            f"user_id为：{user_id} ，名称：{nick_name}，"
            f"置信度{yolo_conf:.2f}，device_id: 1。区域是：小仓库。"
        )
        
        logger.info(f"Uploading Full Record to Agent: {query}")
        try:
            response = self.to_agent.invoke(query=query)
            logger.info(f"Agent Response: {response}")
        except Exception as e:
            logger.error(f"Error invoking Agent: {e}")

    def _update_local_json_end_time(self, end_time_str: str) -> List[Dict[str, Any]]:
        """
        Scans the daily JSONL file for open records and updates them.
        Returns a list of the records that were just closed.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        log_dir = os.path.join(project_root, 'logs', 'person')
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
                        try:
                            start_dt = datetime.fromisoformat(record['start_time'])
                            end_dt = datetime.fromisoformat(end_time_str)
                            record['duration_seconds'] = (end_dt - start_dt).total_seconds()
                        except:
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

if __name__ == "__main__":
    tc = TimeCapture()
    try:
        tc.start_monitoring()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        tc.stop_monitoring()
