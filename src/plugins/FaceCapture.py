# -*- coding: utf-8 -*-
"""
Face Capture Plugin for Warehouse Monitoring System.

This module handles:
1. Real-time face detection using YOLOv5n.
2. Identity recognition via external API.
3. Reporting entry events to the central agent.
4. Managing session cooldowns to prevent spamming.
"""

import warnings
import cv2
import numpy as np
import requests
import json
import os
import sys
import torch
import concurrent.futures
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

# Suppress FutureWarning from torch/numpy
warnings.filterwarnings("ignore", category=FutureWarning)

# Configure logger
logger = logging.getLogger("FaceCapture")

# Ensure project root is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

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

FACE_API_URL = "http://192.168.11.24:8088/system/visitorRecord/recognizeFace"
CONFIDENCE_THRESHOLD = 0.6
MIN_DETECTION_DURATION = 0.25  # Seconds
MIN_FACE_AREA_RATIO = 0.08     # 8% of frame
MAX_REPORT_COUNT = 2           # Max reports per session
COOLDOWN_DURATION = 60.0       # Seconds
REPORT_INTERVAL = 0.5          # Seconds

# ================= Face Capture Service =================

class FaceCapture:
    """
    Service for detecting and recognizing faces from the camera feed.
    """

    def __init__(self, model=None, model_lock=None):
        self.face_api_url = FACE_API_URL
        self.bj_tz = timezone(timedelta(hours=8))
        self.to_agent = ToAgent() if ToAgent else None
        
        # Configuration
        self.headless = os.environ.get('HEADLESS', 'False').lower() == 'true'
        
        # State Management
        self.identified_cooldowns: Dict[str, float] = {}  # {user_id: expiry_timestamp}
        self.person_states: Dict[str, Dict] = {}          # {user_id: {'count': 0, 'cooldown_until': 0}}
        self.state_lock = threading.Lock()
        
        # Thread Pool for async API calls
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        
        # Resources
        self.cap = None
        self.model = model
        self.model_lock = model_lock

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
            logger.critical(f"Error loading model: {e}")
            sys.exit(1)

    def _initialize_camera(self):
        """Initialize the video capture device."""
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            logger.error("Could not open camera 0.")
            return False
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Headless detection logic
        if not self.headless:
            if not os.environ.get('DISPLAY'):
                logger.warning("No DISPLAY detected. Switching to HEADLESS mode.")
                self.headless = True
            else:
                try:
                    # Test display capability
                    cv2.imshow("Test", np.zeros((10, 10, 3), dtype=np.uint8))
                    cv2.destroyWindow("Test")
                except Exception as e:
                    logger.warning(f"Display not available ({e}). Switching to HEADLESS mode.")
                    self.headless = True
        return True

    def start_monitoring(self):
        """Start the main monitoring loop."""
        logger.info("Starting FaceCapture Monitoring Service...")
        
        if not self._initialize_camera():
            return

        if self.model is None:
            self.load_model()
            
        logger.info("Camera and Model Ready. Monitoring started.")

        # Local state for the loop
        is_tracking = False
        session_report_count = 0
        session_start_time = None
        last_seen_time = 0.0
        
        # Debounce state
        potential_start_time = 0.0
        is_potential_entry = False
        tracking_timeout = 5.0
        last_scene_recognition_time = 0.0

        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    logger.warning("Failed to grab frame. Retrying...")
                    time.sleep(0.1)
                    continue

                current_time = datetime.now().timestamp()
                
                # Cleanup expired cooldowns
                self._cleanup_cooldowns(current_time)

                # Run Inference
                if self.model_lock:
                    with self.model_lock:
                        results = self.model(frame)
                else:
                    results = self.model(frame)
                    
                detections = results.xyxy[0].cpu().numpy()
                
                valid_detections = []
                frame_area = float(frame.shape[0] * frame.shape[1])
                person_detected_now = False

                for *xyxy, conf, cls in detections:
                    if conf >= CONFIDENCE_THRESHOLD and int(cls) == 0:
                        x1, y1, x2, y2 = map(int, xyxy)
                        
                        # Filter small objects
                        box_area = (x2 - x1) * (y2 - y1)
                        if box_area / frame_area < MIN_FACE_AREA_RATIO:
                            if not self.headless:
                                cv2.rectangle(frame, (x1, y1), (x2, y2), (100, 100, 100), 1)
                            continue

                        person_detected_now = True
                        valid_detections.append((x1, y1, x2, y2, float(conf)))
                        
                        if not self.headless:
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # --- State Machine Logic ---
                if person_detected_now:
                    last_seen_time = current_time
                    
                    if not is_tracking:
                        # Entry Phase
                        if not is_potential_entry:
                            is_potential_entry = True
                            potential_start_time = current_time
                        else:
                            if current_time - potential_start_time >= MIN_DETECTION_DURATION:
                                # Confirmed Entry
                                is_tracking = True
                                session_report_count = 0
                                is_potential_entry = False
                                session_start_time = self.get_bj_time()
                                
                                # Immediate recognition
                                self.process_frame_for_identities(frame, current_time, detections=valid_detections)
                                session_report_count += 1
                    else:
                        # Tracking Phase
                        if current_time - last_scene_recognition_time >= REPORT_INTERVAL:
                            if session_report_count < MAX_REPORT_COUNT:
                                self.process_frame_for_identities(frame, current_time, detections=valid_detections)
                                last_scene_recognition_time = current_time
                                session_report_count += 1
                else:
                    # No person detected
                    if is_potential_entry:
                        is_potential_entry = False
                        
                    if is_tracking:
                        if current_time - last_seen_time > tracking_timeout:
                            logger.info(f"Session ended. Started at {session_start_time}")
                            is_tracking = False

                # UI Display
                if not self.headless:
                    self._draw_debug_info(frame, current_time)
                    cv2.imshow('FaceCapture Monitor', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                        
        except KeyboardInterrupt:
            logger.info("Stopping monitoring...")
        finally:
            if self.cap:
                self.cap.release()
            cv2.destroyAllWindows()

    def _cleanup_cooldowns(self, current_time: float):
        """Remove expired entries from identified_cooldowns."""
        expired = [uid for uid, ts in self.identified_cooldowns.items() if current_time > ts]
        for uid in expired:
            del self.identified_cooldowns[uid]

    def _draw_debug_info(self, frame, current_time: float):
        """Draw debug overlays on the frame."""
        y_off = 30
        for uid, ts in self.identified_cooldowns.items():
            rem = int(ts - current_time)
            cv2.putText(frame, f"Cooldown {uid}: {rem}s", (10, y_off), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            y_off += 20

    def process_frame_for_identities(self, frame: np.ndarray, current_time: float, 
                                   detections: List[Tuple] = None):
        """
        Process detected persons in the frame: crop, encode, and recognize.
        """
        bj_time = self.get_bj_time()
        targets_to_process = []
        
        if detections:
            h, w, _ = frame.shape
            for det in detections:
                x1, y1, x2, y2 = det[:4]
                conf = det[4]
                
                # Add 10% padding
                pad_x = int((x2 - x1) * 0.1)
                pad_y = int((y2 - y1) * 0.1)
                crop_x1 = max(0, x1 - pad_x)
                crop_y1 = max(0, y1 - pad_y)
                crop_x2 = min(w, x2 + pad_x)
                crop_y2 = min(h, y2 + pad_y)
                
                crop_img = frame[crop_y1:crop_y2, crop_x1:crop_x2]
                if crop_img.size > 0:
                    targets_to_process.append((crop_img.copy(), conf))
        else:
            # Fallback: full frame
            targets_to_process.append((frame.copy(), 0.0))

        logger.debug(f"Async processing {len(targets_to_process)} target(s)...")

        for img_idx, (img, conf) in enumerate(targets_to_process):
            self.executor.submit(
                self._async_recognize_task, img, current_time, bj_time, img_idx, conf
            )

    def _async_recognize_task(self, img_to_send, current_time, bj_time, img_idx, conf):
        """Worker task for face recognition."""
        try:
            # 1. API Call
            result = self.capture_and_recognize(img_to_send, bj_time, suffix=f"_{img_idx}")
            if not result:
                return

            # 2. Extract Data
            user_id = "unknown"
            nick_name = "Unknown"
            user_type = "Unknown"
            
            if isinstance(result, dict) and result.get("code") == 200:
                data = result.get("data", {})
                if data:
                    user_id = str(data.get("userId", "unknown"))
                    nick_name = data.get("nickName", "Unknown")
                    user_type = data.get("userType", "Unknown")

            # 3. Filter Invalid Users
            if self._should_ignore_user(user_id, nick_name, user_type):
                return

            # 4. Check Cooldown
            with self.state_lock:
                in_cooldown = user_id in self.identified_cooldowns
            
            if in_cooldown:
                logger.debug(f"User {nick_name} is in cooldown.")
                return 

            # 5. Process Valid Report
            logger.info(f"Recognized: {nick_name} ({user_id})")
            with self.state_lock:
                self._update_person_state(user_id, nick_name, current_time, result, bj_time, conf)

        except Exception as e:
            logger.error(f"Async Task Error: {e}")

    def _should_ignore_user(self, user_id: str, nick_name: str, user_type: str) -> bool:
        """Determine if the recognized user should be ignored."""
        if "游客" in user_type or "visitor" in user_type.lower():
            logger.info(f"Ignored Visitor: {nick_name}")
            return True
            
        if not user_id or user_id.lower() in ["unknown", "none", ""] or not nick_name:
            logger.debug(f"Ignored Unknown User (ID: {user_id})")
            return True
            
        return False

    def _update_person_state(self, user_id, nick_name, current_time, face_result, bj_time, conf):
        """Update report counters and trigger logging/sending."""
        state = self.person_states.get(user_id, {'count': 0, 'cooldown_until': 0.0})
        
        if current_time < state['cooldown_until']:
            return

        state['count'] += 1
        logger.info(f"Reporting {nick_name} ({state['count']}/{MAX_REPORT_COUNT})")
        
        record = {
            "start_time": bj_time.isoformat(),
            "face_result": face_result,
            "person_name": nick_name,
            "event_type": "realtime_identification",
            "yolo_confidence": float(conf)
        }
        
        # Only log/send on first detection of the session
        if state['count'] == 1:
            self.save_local_json(record)
            self.send_to_agent(record)
        
        # Check if max reports reached -> Enter Cooldown
        if state['count'] >= MAX_REPORT_COUNT:
            logger.info(f"{nick_name} reached max reports. Cooldown for {COOLDOWN_DURATION}s.")
            state['cooldown_until'] = current_time + COOLDOWN_DURATION
            state['count'] = 0
            
            # Also update global cooldown map for quick lookup
            self.identified_cooldowns[user_id] = state['cooldown_until']
            
        self.person_states[user_id] = state

    def capture_and_recognize(self, frame, timestamp: datetime, suffix="") -> Optional[Dict[str, Any]]:
        """Encode image and send to API."""
        try:
            filename = timestamp.strftime(f"%Y%m%d-%H%M%S_face{suffix}.jpg")
            success, encoded_img = cv2.imencode('.jpg', frame)
            
            if not success:
                logger.error("Failed to encode image.")
                return None
            
            files = {'file': (filename, encoded_img.tobytes(), 'image/jpeg')}
            
            logger.debug(f"Sending face image {filename} to API...")
            response = requests.post(self.face_api_url, files=files, timeout=30)
            
            try:
                result = response.json()
                return result
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON response: {response.text}")
                return {"raw": response.text}
                
        except Exception as e:
            logger.error(f"API Request Error: {e}")
            return None

    def send_to_agent(self, record: Dict[str, Any]):
        """Send entry event to Agent (without end_time)."""
        if not self.to_agent:
            return

        try:
            start_t = record.get('start_time')
            face_res = record.get('face_result', {})
            yolo_conf = record.get('yolo_confidence', 0.95)
            
            try:
                s_dt = datetime.fromisoformat(start_t)
                start_str = f"{s_dt.hour}点{s_dt.minute:02d}分"
            except (ValueError, TypeError):
                start_str = start_t
                
            user_id = "Unknown"
            nick_name = "Unknown"
            if isinstance(face_res, dict) and face_res.get("code") == 200:
                data = face_res.get("data", {})
                user_id = data.get("userId", "Unknown")
                nick_name = data.get("nickName", "Unknown")
                 
            query = (
                f"检测到人员进入：时间 {start_str}，"
                f"user_id为：{user_id} ，名称：{nick_name}，"
                f"置信度{yolo_conf:.2f}，device_id: 1。区域是：小仓库入口。"
            )
            
            logger.info(f"Sending Entry Event to Agent: {query}")
            self.to_agent.invoke(query=query)
            
        except Exception as e:
            logger.error(f"Error sending to Agent: {e}")

    def save_local_json(self, record: Dict[str, Any]):
        """Save record to local JSONL file."""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            log_dir = os.path.join(project_root, 'logs', 'person')
            os.makedirs(log_dir, exist_ok=True)
            
            file_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")
            
            # Remove redundant field if exists
            record.pop('person_name', None)
                
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Error saving local JSON: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    plugin = FaceCapture()
    plugin.start_monitoring()
