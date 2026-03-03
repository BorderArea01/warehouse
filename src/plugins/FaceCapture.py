# -*- coding: utf-8 -*-
"""
Face Capture Plugin for Warehouse Monitoring System (MediaPipe Version).

This module handles:
1. Real-time person detection using MediaPipe ObjectDetector (EfficientDet).
2. Identity recognition via external API.
3. Reporting entry events to the central agent.
4. Managing session cooldowns.
"""

import time
import cv2
import numpy as np
import requests
import json
import os
import sys
import concurrent.futures
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

# MediaPipe Imports
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Local Imports
from src.config import Config
try:
    from src.plugins.ToAgent import ToAgent
    from src.plugins.MinioUploader import MinioUploader
except ImportError:
    ToAgent = None
    MinioUploader = None

# Configure logger
logger = Config.get_logger("FaceCapture")

# ================= Face Capture Service =================

class FaceCapture:
    """
    Service for detecting persons and recognizing faces.
    """

    def __init__(self, model_path: str):
        self.face_api_url = Config.FACE_API_URL
        self.bj_tz = timezone(timedelta(hours=8))
        self.to_agent = ToAgent(module_name="FaceCapture") if ToAgent else None
        self.uploader = MinioUploader() if MinioUploader else None
        self.model_path = model_path
        
        # Configuration
        self.headless = os.environ.get('HEADLESS', 'False').lower() == 'true'
        
        # State Management
        self.identified_cooldowns: Dict[str, float] = {}
        self.person_states: Dict[str, Dict] = {}
        self.state_lock = threading.Lock()
        
        # Thread Pool
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self._inflight_lock = threading.Lock()
        self._inflight_tasks = 0
        self._max_inflight_tasks = 6
        self._open_user_cache = set()
        self._open_cache_last_refresh = 0.0
        self._open_cache_refresh_interval = 5.0
        self._open_cache_day = None
        
        # Resources
        self.cap = None
        self.detector = None

    def get_bj_time(self) -> datetime:
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
                score_threshold=Config.FACE_CONFIDENCE_THRESHOLD,
                max_results=5,
                category_allowlist=["person"]
            )
            self.detector = vision.ObjectDetector.create_from_options(options)
            logger.debug("MediaPipe Object Detector loaded successfully.")
        except Exception as e:
            logger.critical(f"Failed to load MediaPipe model: {e}")
            sys.exit(1)

    def _initialize_camera(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            logger.error("Could not open camera 0.")
            return False
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        if not self.headless:
            if not os.environ.get('DISPLAY'):
                self.headless = True
            else:
                try:
                    # Test display
                    cv2.imshow("Test", np.zeros((10, 10, 3), dtype=np.uint8))
                    cv2.destroyWindow("Test")
                except Exception:
                    self.headless = True
        return True

    def start_monitoring(self):
        """Start the main monitoring loop."""
        logger.debug("Starting FaceCapture Monitoring Service...")
        
        if not self._initialize_camera():
            return

        self._init_detector()

        # Loop State
        is_tracking = False
        session_report_count = 0
        session_start_time = None
        last_seen_time = 0.0
        
        # Debounce
        potential_start_time = 0.0
        is_potential_entry = False
        tracking_timeout = 5.0
        last_scene_recognition_time = 0.0
        read_fail_count = 0
        last_reinit_time = 0.0
        
        min_detection_duration = Config.FACE_MIN_DETECTION_DURATION
        # min_face_area_ratio is not in config, using constant logic or hardcoded
        min_face_area_ratio = 0.08
        report_interval = 1.0

        try:
            while True:
                try:
                    ret, frame = self.cap.read()
                    if not ret:
                        read_fail_count += 1
                        now = time.time()
                        if read_fail_count >= 30 and now - last_reinit_time >= 5.0:
                            if self.cap:
                                self.cap.release()
                            self._initialize_camera()
                            last_reinit_time = now
                            read_fail_count = 0
                        time.sleep(0.1)
                        continue

                    read_fail_count = 0
                    current_time = time.time()
                    self._cleanup_cooldowns(current_time)

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    
                    detection_result = self.detector.detect(mp_image)
                    detections = detection_result.detections
                    
                    valid_detections = []
                    frame_area = float(frame.shape[0] * frame.shape[1])
                    person_detected_now = False

                    for detection in detections:
                        bbox = detection.bounding_box
                        x1 = int(bbox.origin_x)
                        y1 = int(bbox.origin_y)
                        w_box = int(bbox.width)
                        h_box = int(bbox.height)
                        x2 = x1 + w_box
                        y2 = y1 + h_box
                        
                        score = detection.categories[0].score

                        box_area = w_box * h_box
                        if box_area / frame_area < min_face_area_ratio:
                            if not self.headless:
                                cv2.rectangle(frame, (x1, y1), (x2, y2), (100, 100, 100), 1)
                            continue

                        person_detected_now = True
                        valid_detections.append((x1, y1, x2, y2, float(score)))
                        
                        if not self.headless:
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(frame, f"Person {score:.2f}", (x1, y1 - 10), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                    if person_detected_now:
                        last_seen_time = current_time
                        
                        if not is_tracking:
                            if not is_potential_entry:
                                is_potential_entry = True
                                potential_start_time = current_time
                            else:
                                if current_time - potential_start_time >= min_detection_duration:
                                    is_tracking = True
                                    session_report_count = 0
                                    is_potential_entry = False
                                    session_start_time = self.get_bj_time()
                                    
                                    self.process_frame_for_identities(frame, current_time, detections=valid_detections)
                                    session_report_count += 1
                        else:
                            if current_time - last_scene_recognition_time >= report_interval:
                                self.process_frame_for_identities(frame, current_time, detections=valid_detections)
                                last_scene_recognition_time = current_time
                                session_report_count += 1
                    else:
                        if is_potential_entry:
                            is_potential_entry = False
                            
                        if is_tracking:
                            if current_time - last_seen_time > tracking_timeout:
                                logger.info(f"Session ended. Started at {session_start_time}")
                                is_tracking = False

                    if not self.headless:
                        self._draw_debug_info(frame, current_time)
                        cv2.imshow('FaceCapture Monitor', frame)
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            break
                except Exception as e:
                    logger.error(f"Monitoring Loop Error: {e}")
                    time.sleep(0.1)
                        
        except KeyboardInterrupt:
            logger.info("Stopping monitoring...")
        finally:
            if self.cap:
                self.cap.release()
            try:
                self.executor.shutdown(wait=False)
            except Exception:
                pass
            self.detector = None
            cv2.destroyAllWindows()

    def _cleanup_cooldowns(self, current_time: float):
        expired = [uid for uid, ts in self.identified_cooldowns.items() if current_time > ts]
        for uid in expired:
            del self.identified_cooldowns[uid]

    def _draw_debug_info(self, frame, current_time: float):
        y_off = 30
        for uid, ts in self.identified_cooldowns.items():
            rem = int(ts - current_time)
            cv2.putText(frame, f"Cooldown {uid}: {rem}s", (10, y_off), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            y_off += 20

    def process_frame_for_identities(self, frame: np.ndarray, current_time: float, 
                                   detections: List[Tuple] = None):
        """Process detected persons: crop and recognize."""
        bj_time = self.get_bj_time()
        targets_to_process = []
        
        if detections:
            h, w, _ = frame.shape
            for det in detections:
                x1, y1, x2, y2 = det[:4]
                conf = det[4]
                
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
            targets_to_process.append((frame.copy(), 0.0))

        logger.debug(f"Async processing {len(targets_to_process)} target(s)...")

        for img_idx, (img, conf) in enumerate(targets_to_process):
            with self._inflight_lock:
                if self._inflight_tasks >= self._max_inflight_tasks:
                    continue
                self._inflight_tasks += 1
            self.executor.submit(
                self._async_recognize_task, img, current_time, bj_time, img_idx, conf
            )

    def _async_recognize_task(self, img_to_send, current_time, bj_time, img_idx, conf):
        try:
            # API Call
            result = self.capture_and_recognize(img_to_send, bj_time, suffix=f"_{img_idx}")
            if not result:
                return

            user_id = "unknown"
            nick_name = "Unknown"
            user_type = "Unknown"
            
            if isinstance(result, dict) and result.get("code") == 200:
                data = result.get("data", {})
                if data:
                    user_id = str(data.get("userId", "unknown"))
                    nick_name = data.get("nickName", "Unknown")
                    user_type = data.get("userType", "Unknown")
            else:
                logger.warning(f"API returned non-200 or invalid format: {result}")

            if self._should_ignore_user(user_id, nick_name, user_type):
                # logger.warning(f"Ignored user from API: id={user_id}, name={nick_name}, type={user_type}")
                return

            with self.state_lock:
                in_cooldown = user_id in self.identified_cooldowns
            
            if in_cooldown:
                return 

            # Check visitor status
            is_visitor = "游客" in nick_name or "visitor" in nick_name.lower() or "游客" in user_type or "visitor" in user_type.lower()
            
            if is_visitor:
                # Terminal only, minimal output
                print(f"[Visitor] Detected: {nick_name} ({user_id})")
                # Skip normal logging and upload for visitors to keep logs clean
                # Only update state to handle cooldown
                with self.state_lock:
                    self._update_person_state(user_id, nick_name, current_time, result, bj_time, conf, image_url="无")
                return

            logger.info(f"Recognized: {nick_name} ({user_id})")

            # Upload Image to MinIO
            image_url = "无"
            if self.uploader:
                try:
                    temp_filename = f"temp_face_{int(current_time*1000)}.jpg"
                    log_dir = Path(Config.PROJECT_ROOT) / "logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    temp_path = log_dir / temp_filename
                    cv2.imwrite(str(temp_path), img_to_send)
                    
                    upload_res = self.uploader.upload_file(temp_path)
                    if upload_res:
                        image_url = upload_res.get('fileUrl', upload_res.get('url', str(upload_res)))
                    
                    if temp_path.exists():
                        temp_path.unlink()
                        
                except Exception as e:
                    logger.error(f"Image Upload Failed: {e}")

            with self.state_lock:
                self._update_person_state(user_id, nick_name, current_time, result, bj_time, conf, image_url)

        except Exception as e:
            logger.error(f"Async Task Error: {e}")
        finally:
            with self._inflight_lock:
                self._inflight_tasks = max(0, self._inflight_tasks - 1)

    def _should_ignore_user(self, user_id: str, nick_name: str, user_type: str) -> bool:
        # if "游客" in user_type or "visitor" in user_type.lower():
        #     logger.warning(f"🚫 Blocked Visitor: {nick_name} (Access Denied)")
        #     return True
            
        if not user_id or user_id.lower() in ["unknown", "none", ""] or not nick_name:
            # logger.warning(f"🚫 Ignored Invalid Identity: ID='{user_id}', Name='{nick_name}'")
            return True
            
        return False

    def _update_person_state(self, user_id, nick_name, current_time, face_result, bj_time, conf, image_url="无"):
        is_visitor = "游客" in nick_name or "visitor" in nick_name.lower()
        if not is_visitor and isinstance(face_result, dict):
            u_type = face_result.get("data", {}).get("userType", "")
            if "游客" in u_type or "visitor" in u_type.lower():
                is_visitor = True
        
        cooldown_duration = 1.0 if is_visitor else 5.0
        
        state = self.person_states.get(user_id, {'cooldown_until': 0.0})
        
        if current_time < state['cooldown_until']:
            return

        if self._is_user_already_in(user_id):
            logger.info(f"User {nick_name} is already in warehouse (Open Record). Skipping new entry log.")
            state['cooldown_until'] = current_time + cooldown_duration
            self.identified_cooldowns[user_id] = state['cooldown_until']
            self.person_states[user_id] = state
            return

        if is_visitor:
            # For visitors, we already printed in terminal. Just update cooldown and exit.
            state['cooldown_until'] = current_time + cooldown_duration
            self.identified_cooldowns[user_id] = state['cooldown_until']
            self.person_states[user_id] = state
            return

        logger.info(f"Reporting Entry: {nick_name} (Cooldown: {cooldown_duration}s)")
        
        record = {
            "start_time": bj_time.strftime("%Y-%m-%d %H:%M:%S"),
            "face_result": face_result,
            "person_name": nick_name,
            "event_type": "realtime_identification",
            "confidence": float(conf),
            "user_id": user_id,
            "image_url": image_url
        }
        
        self.save_local_json(record)
        self.send_to_agent(record)
        
        state['cooldown_until'] = current_time + cooldown_duration
        self.identified_cooldowns[user_id] = state['cooldown_until']
        self.person_states[user_id] = state

    def _is_user_already_in(self, user_id: str) -> bool:
        try:
            self._refresh_open_user_cache()
            return str(user_id) in self._open_user_cache
        except Exception as e:
            logger.error(f"Error checking open records: {e}")
            return False

    def _refresh_open_user_cache(self):
        now = time.time()
        today_str = datetime.now().strftime("%Y-%m-%d")
        if self._open_cache_day != today_str:
            self._open_user_cache = set()
            self._open_cache_day = today_str
            self._open_cache_last_refresh = 0.0
        if now - self._open_cache_last_refresh < self._open_cache_refresh_interval:
            return
        self._open_cache_last_refresh = now
        log_dir = os.path.join(Config.PROJECT_ROOT, 'logs', 'person')
        file_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")
        if not os.path.exists(file_path):
            self._open_user_cache = set()
            return
        open_map = {}
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec_uid = rec.get("user_id")
                if not rec_uid:
                    face_res = rec.get("face_result", {})
                    if isinstance(face_res, dict) and face_res.get("code") == 200:
                        rec_uid = str(face_res.get("data", {}).get("userId", ""))
                if not rec_uid:
                    continue
                if rec.get("event_type") == "completed_visit" or rec.get("end_time"):
                    open_map[str(rec_uid)] = False
                else:
                    open_map[str(rec_uid)] = True
        self._open_user_cache = {uid for uid, opened in open_map.items() if opened}

    def capture_and_recognize(self, frame, timestamp: datetime, suffix="") -> Optional[Dict[str, Any]]:
        try:
            filename = timestamp.strftime(f"%Y%m%d-%H%M%S_face{suffix}.jpg")
            success, encoded_img = cv2.imencode('.jpg', frame)
            
            if not success:
                return None
            
            files = {'file': (filename, encoded_img.tobytes(), 'image/jpeg')}
            response = requests.post(self.face_api_url, files=files, timeout=30)
            
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"raw": response.text}
        except Exception as e:
            logger.error(f"API Request Error: {e}")
            return None

    def send_to_agent(self, record: Dict[str, Any]):
        if not self.to_agent:
            return

        try:
            start_t = record.get('start_time')
            face_res = record.get('face_result', {})
            conf = record.get('confidence', 0.95)
            img_url = record.get('image_url', '无')
            
            start_str = start_t
            try:
                if 'T' in start_str:
                    s_dt = datetime.fromisoformat(start_str)
                    start_str = s_dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass
                
            user_id = "Unknown"
            nick_name = "Unknown"
            if isinstance(face_res, dict) and face_res.get("code") == 200:
                data = face_res.get("data", {})
                user_id = data.get("userId", "Unknown")
                nick_name = data.get("nickName", "Unknown")

            api_url = "http://192.168.11.24:8088/open/workflow/execute"
            headers = {
                "X-API-Key": "wf_6356a9907849423ba0d3c5510c60f64a",
                "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
                "Content-Type": "application/json",
                "Host": "192.168.11.24:8088",
                "Connection": "keep-alive"
            }

            inputs = {
                "device_id": "1",
                "zone": "小仓库",
                "image_url": img_url,
                "person_id": str(user_id)
            }

            payload = {
                "workflowId": "2027306314434215938",
                "inputs": inputs
            }

            # ANSI Colors
            COLOR_REQ = "\033[96m"
            COLOR_RES = "\033[94m"
            COLOR_RESET = "\033[0m"

            log_req = (
                f"\n{COLOR_REQ}{'='*30}\n"
                f"[发送] Module: FaceCapture\n"
                f"Sending: {json.dumps(payload, ensure_ascii=False, indent=2)}\n"
                f"{'='*30}{COLOR_RESET}"
            )
            logger.info(log_req)

            resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
            
            try:
                resp_data = resp.json()
                log_resp = (
                    f"\n{COLOR_RES}{'='*30}\n"
                    f"[返回] Module: FaceCapture\n"
                    f"Status: {resp.status_code}\n"
                    f"Response: {json.dumps(resp_data, ensure_ascii=False, indent=2)}\n"
                    f"{'='*30}{COLOR_RESET}"
                )
                logger.info(log_resp)
            except ValueError:
                log_resp = (
                    f"\n{COLOR_RES}{'='*30}\n"
                    f"[返回] Module: FaceCapture\n"
                    f"Status: {resp.status_code}\n"
                    f"Response: {resp.text[:200]}...\n"
                    f"{'='*30}{COLOR_RESET}"
                )
                logger.info(log_resp)
            
        except Exception as e:
            logger.error(f"Error sending to Agent: {e}")

    def save_local_json(self, record: Dict[str, Any]):
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            log_dir = os.path.join(Config.PROJECT_ROOT, 'logs', 'person')
            os.makedirs(log_dir, exist_ok=True)
            file_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")
            
            record.pop('person_name', None)
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Error saving local JSON: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Run via main.py to ensure model path is provided.")
