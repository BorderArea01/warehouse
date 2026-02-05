
import cv2
import time
import os
import sys
import threading
import json
import torch
import warnings
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

# Suppress PyTorch warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

try:
    from src.plugins.ToAgent import ToAgent
except ImportError:
    sys.path.append(os.path.join(project_root, 'src', 'plugins'))
    try:
        from ToAgent import ToAgent
    except ImportError:
        print("Warning: Could not import ToAgent")
        ToAgent = None

import fileinput

class TimeCapture:
    """
    TimeCapture Plugin:
    - Monitors the Warehouse Camera (Hikvision RTSP) for person exit events.
    - Runs in a separate thread/async mode.
    - Updates the database (via Agent) AND the local JSONL file with the end time.
    """
    def __init__(self):
        # Configuration
        self.rtsp_url = "rtsp://admin:Lzwc%402025.@192.168.13.140:554/Streaming/Channels/101"
        self.bj_tz = timezone(timedelta(hours=8))
        self.to_agent = ToAgent() if ToAgent else None
        
        self.json_path = os.path.join(project_root, 'visit_records.jsonl')
        
        # Detection Config
        self.confidence_threshold = 0.5
        self.person_timeout = 5.0 # Seconds of no person seen to consider "Left"
        
        self.running = False
        self.monitor_thread = None
        self.model = None

    def get_bj_time(self) -> datetime:
        return datetime.now(self.bj_tz)

    def load_model(self):
        print("[TimeCapture] Loading YOLOv5n model...")
        try:
            self.model = torch.hub.load('ultralytics/yolov5', 'yolov5n', pretrained=True)
            self.model.classes = [0]  # Filter to 'person' class
        except Exception as e:
            print(f"[TimeCapture] Error loading model: {e}")

    def start_monitoring(self):
        """
        Starts the background monitoring thread.
        """
        if self.running:
            print("[TimeCapture] Already running.")
            return

        if self.model is None:
            self.load_model()

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("[TimeCapture] Monitoring started in background thread.")

    def stop_monitoring(self):
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        print("[TimeCapture] Monitoring stopped.")

    def _monitor_loop(self):
        """
        Main loop to read RTSP stream and detect person presence.
        Logic:
        - If person seen: Update last_seen_time.
        - If person NOT seen for > timeout: Trigger Exit Event.
        """
        cap = cv2.VideoCapture(self.rtsp_url)
        if not cap.isOpened():
            print(f"[TimeCapture] Error: Could not open RTSP stream: {self.rtsp_url}")
            self.running = False
            return

        # Optimization: Skip frames to reduce load (process every 5th frame)
        frame_count = 0
        skip_frames = 5
        
        # State
        person_present = False
        last_seen_time = time.time()
        is_session_active = False # Are we currently tracking a visit?
        session_start_marker = 0

        print("[TimeCapture] Connected to Camera. Listening for exit events...")

        while self.running:
            ret, frame = cap.read()
            if not ret:
                print("[TimeCapture] Stream disconnected. Reconnecting in 5s...")
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
                    session_start_marker = current_time
                    print(f"[TimeCapture] Person Detected in Warehouse. Tracking session...")
            
            else:
                if is_session_active:
                    # Person was here, now gone. Check timeout.
                    duration_gone = current_time - last_seen_time
                    if duration_gone > self.person_timeout:
                        # TIMEOUT REACHED -> EVENT END
                        end_time = self.get_bj_time()
                        print(f"[TimeCapture] Person Left Warehouse (Timeout {self.person_timeout}s). End Time: {end_time}")
                        
                        # Trigger Agent to update DB
                        self.report_exit_event(end_time)
                        
                        is_session_active = False

            # Optional: Sleep to save CPU
            time.sleep(0.1)

        cap.release()

    def report_exit_event(self, end_time: datetime):
        """
        1. Updates local JSONL file with end_time for the last record.
        2. Calls the Agent to update the DB with the FULL record (start + end).
        """
        end_time_str = end_time.isoformat()
        
        # 1. Update Local File and Get Full Records
        closed_records = self.update_local_json_end_time(end_time_str)
        
        # 2. Call Agent for each closed record
        if not self.to_agent:
            print("[TimeCapture] Agent not available. Cannot report exit.")
            return

        if not closed_records:
            print("[TimeCapture] No valid records to upload.")
            return

        for record in closed_records:
            # We now send the COMPLETE record
            start_t = record.get('start_time')
            end_t = record.get('end_time')
            face_res = record.get('face_result', {})
            yolo_conf = record.get('yolo_confidence', 0.95) # Default to 0.95 if missing (as requested example)
            
            # Format times to "16点30分" style
            try:
                s_dt = datetime.fromisoformat(start_t)
                e_dt = datetime.fromisoformat(end_t)
                
                # Format: 16点30分
                start_str = f"{s_dt.hour}点{s_dt.minute:02d}分"
                
                # End time: 17点 (if 00 mins) or 17点05分
                if e_dt.minute == 0:
                     end_str = f"{e_dt.hour}点"
                else:
                     end_str = f"{e_dt.hour}点{e_dt.minute:02d}分"
                     
            except Exception as e:
                print(f"[TimeCapture] Time formatting error: {e}")
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
            
            print(f"[TimeCapture] Uploading Full Record to Agent: {query}")
            try:
                response = self.to_agent.invoke(
                    query=query
                )
                print(f"[TimeCapture] Agent Response: {response}")
            except Exception as e:
                print(f"[TimeCapture] Error invoking Agent: {e}")

    def update_local_json_end_time(self, end_time_str):
        """
        Scans the daily JSONL file for the EARLIEST record that is still 'open' (incomplete).
        Updates it with the end time.
        Returns a list of the records that were just closed.
        """
        # Calculate today's log path (assuming entry was today)
        today_str = datetime.now().strftime("%Y-%m-%d")
        log_dir = os.path.join(project_root, 'logs', 'person')
        self.json_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")

        if not os.path.exists(self.json_path):
            print("[TimeCapture] Warning: Today's JSONL file not found.")
            return []

        closed_records_list = []

        try:
            lines = []
            with open(self.json_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if not lines:
                return []

            # Logic: Close ALL open records
            # When the warehouse is empty, EVERYONE must have left.
            # So we iterate through ALL lines and close any that are "realtime_identification".
            
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
                        
                        # Add to list of records to return
                        closed_records_list.append(record)
                        
                        # Write back to lines list
                        lines[i] = json.dumps(record, ensure_ascii=False) + "\n"
                        updated_count += 1
                except:
                    continue
            
            if updated_count > 0:
                with open(self.json_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                print(f"[TimeCapture] Closed {updated_count} open records. Warehouse is empty.")
            else:
                print("[TimeCapture] No open records found to close.")
                
            return closed_records_list
                
        except Exception as e:
            print(f"[TimeCapture] Error updating local JSON: {e}")
            return []

if __name__ == "__main__":
    # Test Standalone
    tc = TimeCapture()
    try:
        tc.start_monitoring()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        tc.stop_monitoring()
