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
import requests
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
logger = Config.get_logger("TimeCapture")

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

        logger.debug(f"Loading MediaPipe model from {self.model_path}...")
        try:
            base_options = python.BaseOptions(model_asset_path=self.model_path)
            options = vision.ObjectDetectorOptions(
                base_options=base_options,
                score_threshold=self.confidence_threshold,
                max_results=5,
                category_allowlist=["person"]
            )
            self.detector = vision.ObjectDetector.create_from_options(options)
            logger.debug("MediaPipe Object Detector loaded successfully.")
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
        logger.info("TimeCapture Service Started.")

    def stop_monitoring(self):
        """Stop the monitoring thread."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        logger.info("TimeCapture Monitoring stopped.")

    def _monitor_loop(self):
        """Main loop to read RTSP stream and detect person presence."""
        # Set OpenCV environment variables to force TCP (Stable like VLC)
        # Removed 'nobuffer' to allow ffmpeg to smooth out network jitter
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        
        cap = cv2.VideoCapture(self.rtsp_url)
        if not cap.isOpened():
            logger.error(f"Could not open RTSP stream: {self.rtsp_url}")
            
            # Try backup stream if configured
            backup_url = getattr(Config, "RTSP_URL_BACKUP_BASE", None)
            if backup_url:
                logger.info(f"Attempting backup stream: {backup_url}")
                cap = cv2.VideoCapture(backup_url)
                if not cap.isOpened():
                    logger.error("Backup stream also failed.")
                    self.running = False
                    return
            else:
                self.running = False
                return

        logger.info("Connected to Camera. Listening for exit events...")

        # Optimization: Skip frames
        frame_count = 0
        skip_frames = 5
        
        # State
        last_seen_time = time.time()

        # Reader Thread Logic:
        # We separate frame reading from processing to ensure the buffer is drained continuously.
        # This prevents "old" frames from piling up while we are processing (inference).
        # It also mimics VLC's behavior of just playing the stream smoothly.
        
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        
        def _read_frames():
            while self.running and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    # Signal disconnection?
                    time.sleep(0.1)
                    continue
                with self._frame_lock:
                    self._latest_frame = frame.copy()
        
        reader_thread = threading.Thread(target=_read_frames, daemon=True)
        reader_thread.start()

        while self.running:
            # Check if we have a frame
            frame = None
            with self._frame_lock:
                if self._latest_frame is not None:
                    frame = self._latest_frame
                    self._latest_frame = None # Consume it
            
            if frame is None:
                # No new frame yet, or stream issue
                # Check if capture is still valid?
                # For now just sleep and wait
                time.sleep(0.05)
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
                # logger.debug("Person detected - keeping session open.")
            
            else:
                # Person NOT seen. Check how long it has been empty.
                duration_gone = current_time - last_seen_time
                
                if duration_gone > self.person_timeout:
                    # TIMEOUT REACHED -> The room is effectively empty.
                    # Attempt to close ANY open records found on disk.
                    
                    # We define "end_time" as "now" (or when we decided they were gone)
                    # To avoid spamming, _update_local_json_end_time returns empty list if nothing changed.
                    end_time = self.get_bj_time()
                    
                    try:
                        self.report_exit_event(end_time)
                    except Exception as e:
                        logger.error(f"Error in report_exit_event: {e}")
                    
                    # Reset last_seen_time to NOW to prevent re-triggering immediately.
                    # This ensures we wait for another full timeout period or new person detection.
                    last_seen_time = current_time 
                    
                    # Also sleep a bit to be safe
                    time.sleep(1.0) 

            # Optional: Sleep to save CPU
            time.sleep(0.1)

        cap.release()

    def report_exit_event(self, end_time: datetime):
        """
        Handle exit event: update local logs, trigger asset analysis, and report to agent.
        """
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. Update Local File and Get Full Records
        closed_records = self._update_local_json_end_time(end_time_str)
        
        if not closed_records:
            # logger.info("No open records found to close.")
            return

        # Find the earliest start time to cover the entire group visit duration
        start_times = [r.get('start_time') for r in closed_records if r.get('start_time')]
        earliest_start = min(start_times) if start_times else None
        
        # Use the end_time from the first record (all are same)
        end_t = closed_records[0].get('end_time')

        # --- Trigger Asset Analysis and Wait for Result (ONCE) ---
        asset_changes = []
        if self.asset_scanner and earliest_start:
            try:
                asset_changes = self.asset_scanner.get_asset_changes(earliest_start, end_t)
            except Exception as e:
                logger.error(f"Error getting asset changes: {e}")
        
        # Create a master record for reporting
        # Since the report only contains time and assets (not person info), sending one report is sufficient.
        master_record = closed_records[0].copy()
        master_record['asset_changes'] = asset_changes
        
        self._send_record_to_agent(master_record)

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
                 end_str = e_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        
        # Simply send the list of EPC strings
        asset_changes_list = record.get('asset_changes', [])
        
        # query = (
        #     f"生成事件集合\n"
        #     f"时间：{end_str}；\n"
        #     f"区域：小仓库；\n"
        #     f"资产变动情况：{json.dumps(asset_changes_list, ensure_ascii=False)}"
        # )
        api_url = "http://192.168.11.24:8088/open/workflow/execute"
        headers = {
            "X-API-Key": "wf_bf4e77a054364d449618ef7bd7dbe0ac",
            "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
            "Content-Type": "application/json",
            "Host": "192.168.11.24:8088",
            "Connection": "keep-alive"
        }
        
        inputs = {
            "time": str(end_str),
            "zone": "小仓库"
        }
        
        # Only add asset_list if there are changes
        if asset_changes_list:
            # Join list into a comma-separated string: "EPC1,EPC2"
            inputs["asset_list"] = ",".join(str(epc) for epc in asset_changes_list)
            
        payload = {
            "workflowId": "2027307779508797442",
            "inputs": inputs
        }

        # ANSI Colors
        COLOR_REQ = "\033[96m"
        COLOR_RES = "\033[94m"
        COLOR_RESET = "\033[0m"

        log_req = (
            f"\n{COLOR_REQ}{'='*30}\n"
            f"[发送] Module: TimeCapture\n"
            f"Sending: {json.dumps(payload, ensure_ascii=False, indent=2)}\n"
            f"{'='*30}{COLOR_RESET}"
        )
        logger.info(log_req)

        try:
            resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
            
            try:
                resp_data = resp.json()
                log_resp = (
                    f"\n{COLOR_RES}{'='*30}\n"
                    f"[返回] Module: TimeCapture\n"
                    f"Status: {resp.status_code}\n"
                    f"Message: {resp_data.get("data", {}).get("message", "No message")}\n"
                    f"{'='*30}{COLOR_RESET}"
                )
                logger.info(log_resp)
            except ValueError:
                log_resp = (
                    f"\n{COLOR_RES}{'='*30}\n"
                    f"[返回] Module: TimeCapture\n"
                    f"Status: {resp.status_code}\n"
                    f"Response: {resp.text[:200]}...\n"
                    f"{'='*30}{COLOR_RESET}"
                )
                logger.info(log_resp)

        except Exception as e:
            logger.error(f"Error invoking Workflow API: {e}")

    def _update_local_json_end_time(self, end_time_str: str) -> List[Dict[str, Any]]:
        """
        Scans the daily JSONL file for open records and updates them.
        Returns a list of the records that were just closed.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        log_dir = os.path.join(Config.PROJECT_ROOT, 'logs', 'person')
        json_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")

        if not os.path.exists(json_path):
            # logger.warning("Today's JSONL file not found.")
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
                                start_dt = datetime.strptime(start_time_val, "%Y-%m-%d %H:%M:%S")
                                
                            if 'T' in end_time_str:
                                end_dt = datetime.fromisoformat(end_time_str)
                            else:
                                end_dt = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                                
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
