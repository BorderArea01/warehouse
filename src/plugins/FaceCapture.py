# -*- coding: utf-8 -*-
"""
Face Capture Plugin for Warehouse process System (MediaPipe Version).
人脸捕获插件 (MediaPipe版本) - Simplified Version
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
import queue
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

# MediaPipe Imports
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Local Imports
import sys
import os
# Add project root to sys.path to allow running this script directly
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import Config
try:
    from src.plugins.ToAgent import ToAgent
    from src.plugins.MinioUploader import MinioUploader
except ImportError:
    ToAgent = None
    MinioUploader = None

# Configure logger
logger = Config.get_logger("FaceCapture")
logger.propagate = False

# ================= Face Capture Service =================

class FaceCapture:
    """
    Service for detecting persons and recognizing faces.
    人脸识别与抓拍服务 (Simplified: Direct Detection -> Recognition)
    """

    def __init__(self, model_path: str):
        self.face_api_url = Config.FACE_API_URL
        self.face_api_key = Config.FACE_API_KEY
        self.bj_tz = timezone(timedelta(hours=8))
        self.to_agent = ToAgent(module_name="FaceCapture") if ToAgent else None
        self.uploader = MinioUploader() if MinioUploader else None
        self.model_path = model_path
        
        # Configuration
        self.headless = os.environ.get('HEADLESS', 'False').lower() == 'true'
        
        # Cooldown State Management
        # user_id -> timestamp (Per-user cooldown)
        self.user_cooldowns: Dict[str, float] = {}
        # timestamp (Global visitor cooldown)
        self.visitor_cooldown_until: float = 0.0
        
        # Visitor Buffer Logic
        # (timestamp, record)
        self.pending_visitor_report: Optional[Tuple[float, Dict]] = None
        self.visitor_buffer_lock = threading.Lock()
        self.visitor_buffer_duration = Config.FACE_VISITOR_BUFFER_DURATION # Wait to see if user appears
        
        self.state_lock = threading.Lock()
        
        # Thread Pool for Recognition
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self._inflight_lock = threading.Lock()
        self._inflight_tasks = 0
        self._max_inflight_tasks = 4  # Limit concurrent API calls
        
        # Resources
        self.cap = None
        self.detector = None

        # Frame Queue
        self.frame_queue = queue.Queue(maxsize=2) # Keep it small for realtime
        self.stop_event = threading.Event()
        self.capture_thread = None

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
        """
        初始化摄像头。
        优先尝试打开 /dev/video0 (USB摄像头)。
        使用 V4L2 后端，并强制使用 MJPG 格式以支持高分辨率。
        """
        self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        
        if not self.cap.isOpened():
            logger.warning("Failed to open camera 0 with V4L2. Trying default backend...")
            self.cap = cv2.VideoCapture(0)
            
        if not self.cap.isOpened():
            logger.error("Could not open camera 0 (USB Camera). Please check connection and permissions.")
            return False
        
        # 强制使用 MJPG 格式 (对于 1080P USB 摄像头通常必须)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        
        if not self.headless:
            if not os.environ.get('DISPLAY'):
                logger.info("No DISPLAY environment variable found. Switching to Headless mode.")
                self.headless = True
            else:
                try:
                    cv2.imshow("Test", np.zeros((10, 10, 3), dtype=np.uint8))
                    cv2.destroyWindow("Test")
                except Exception as e:
                    logger.warning(f"Display test failed ({e}). Switching to Headless mode.")
                    self.headless = True
        return True

    def _capture_loop(self):
        """Thread function to continuously capture frames."""
        logger.info("Starting Camera Capture Thread...")
        
        if not self._initialize_camera():
             logger.error("Initial camera setup failed in capture thread.")
        
        read_fail_count = 0
        last_reinit_time = 0.0

        while not self.stop_event.is_set():
            if self.cap is None or not self.cap.isOpened():
                now = time.time()
                if now - last_reinit_time >= 5.0:
                    logger.info("Attempting to re-initialize camera...")
                    self._initialize_camera()
                    last_reinit_time = now
                time.sleep(1.0)
                continue

            ret, frame = self.cap.read()
            if not ret:
                read_fail_count += 1
                now = time.time()
                if read_fail_count >= 30 and now - last_reinit_time >= 5.0:
                    logger.warning("Camera read failed repeatedly, re-initializing...")
                    if self.cap:
                        self.cap.release()
                    self._initialize_camera()
                    last_reinit_time = now
                    read_fail_count = 0
                time.sleep(0.1)
                continue
            
            read_fail_count = 0
            
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
            
            try:
                self.frame_queue.put(frame, block=False)
            except queue.Full:
                pass
        
        logger.info("Stopping Camera Capture Thread...")
        if self.cap:
            self.cap.release()
            self.cap = None

    def process(self):
        """Start the main process loop."""
        logger.debug("Starting FaceCapture Process Service (Simplified Mode)...")
        
        self._init_detector()

        self.stop_event.clear()
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()

        try:
            while True:
                try:
                    # Check pending visitor reports
                    self._check_pending_visitor()

                    try:
                        frame = self.frame_queue.get(timeout=0.1) # Reduced timeout to check pending visitors often
                    except queue.Empty:
                        continue
                    
                    current_time = time.time()
                    self._cleanup_cooldowns(current_time)

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    
                    detection_result = self.detector.detect(mp_image)
                    detections = detection_result.detections
                    
                    valid_crops = []
                    
                    # Process detections
                    for detection in detections:
                        bbox = detection.bounding_box
                        x1 = int(bbox.origin_x)
                        y1 = int(bbox.origin_y)
                        w = int(bbox.width)
                        h = int(bbox.height)
                        x2 = x1 + w
                        y2 = y1 + h
                        
                        score = detection.categories[0].score

                        # Minimal size check to avoid noise (optional, keep very loose)
                        if w < 20 or h < 20:
                            continue

                        # Crop face
                        crop_img = self._crop_image(frame, (x1, y1, x2, y2))
                        valid_crops.append((crop_img, score, (x1, y1, x2, y2)))

                        # Draw debug box
                        if not self.headless:
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    # Submit tasks
                    for (crop_img, conf, bbox) in valid_crops:
                        with self._inflight_lock:
                            if self._inflight_tasks >= self._max_inflight_tasks:
                                continue # Skip if busy
                            self._inflight_tasks += 1
                        
                        self.executor.submit(
                            self.recognize_task, crop_img, current_time, conf
                        )

                    # Display debug info
                    if not self.headless:
                        cv2.imshow('FaceCapture Process', frame)
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            break
                            
                except Exception as e:
                    logger.error(f"process Loop Error: {e}")
                        
        except KeyboardInterrupt:
            logger.info("Stopping process...")
        finally:
            self.stop_event.set()
            if self.capture_thread:
                self.capture_thread.join(timeout=2.0)
            
            if self.cap:
                self.cap.release()
                self.cap = None

            try:
                self.executor.shutdown(wait=False)
            except Exception:
                pass
            self.detector = None
            cv2.destroyAllWindows()

    def _check_pending_visitor(self):
        """Check if any pending visitor report should be sent."""
        current_time = time.time()
        to_report = None
        
        with self.visitor_buffer_lock:
            if self.pending_visitor_report:
                ts, record = self.pending_visitor_report
                if current_time - ts > self.visitor_buffer_duration:
                    to_report = record
                    self.pending_visitor_report = None
        
        if to_report:
            # Re-check cooldown just in case
            with self.state_lock:
                if current_time < self.visitor_cooldown_until:
                    return
                # Update cooldown
                self.visitor_cooldown_until = current_time + Config.FACE_COOLDOWN_DURATION
                
            logger.info(f"Reporting Buffered Visitor: {to_report.get('person_name')}")
            self.save_logs(to_report)
            self.send_to_agent(to_report)

    def _crop_image(self, frame, bbox):
        x1, y1, x2, y2 = bbox
        h, w, _ = frame.shape
        
        # Add slight padding
        pad_x = int((x2 - x1) * 0.1)
        pad_y = int((y2 - y1) * 0.1)
        crop_x1 = max(0, x1 - pad_x)
        crop_y1 = max(0, y1 - pad_y)
        crop_x2 = min(w, x2 + pad_x)
        crop_y2 = min(h, y2 + pad_y)
        
        return frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()

    def recognize_task(self, img_to_send, current_time, conf):
        """Async recognition task."""
        try:
            bj_time = datetime.now(self.bj_tz)
            result = self.recognize(img_to_send, bj_time)
            
            if not result:
                return

            user_id = "unknown"
            nick_name = "Unknown"
            user_type = "Unknown"
            
            # Parse CompreFace standard response format
            # Example: {"result": [{"box": {...}, "subjects": [{"subject": "Name_ID", "similarity": 0.99}]}]}
            if isinstance(result, dict) and "result" in result and len(result["result"]) > 0:
                first_face = result["result"][0]
                subjects = first_face.get("subjects", [])
                
                if subjects and len(subjects) > 0:
                    best_match = subjects[0]
                    subject_name = best_match.get("subject", "")
                    similarity = best_match.get("similarity", 0.0)
                    
                    if similarity > 0.85: # Set confidence threshold
                        # Parse Subject format: "Type_Name_ID" or "Name_ID"
                        # Rule: Extract the last part as UserID
                        parts = subject_name.split("_")
                        if len(parts) >= 2:
                            user_id = parts[-1] 
                            # If 3 or more parts, take the middle part as name
                            if len(parts) >= 3:
                                nick_name = parts[1]
                            else:
                                nick_name = parts[0]
                        else:
                            # Fallback: Single part
                            nick_name = subject_name
                            user_id = subject_name
                        
                        # Identify Visitor
                        if "游客" in subject_name or "visitor" in subject_name.lower():
                            user_type = "Visitor"
                        else:
                            user_type = "User"
                    else:
                        logger.debug(f"Face recognized but similarity too low: {similarity}")
            else:
                logger.debug(f"CompreFace returned no valid subjects: {result}")
            
            # Check for invalid ID
            if self._should_ignore_user(user_id, nick_name, user_type):
                return

            # Check Cooldowns
            is_visitor = "游客" in nick_name or "visitor" in nick_name.lower() or "游客" in user_type or "visitor" in user_type.lower()
            
            cooldown_duration = Config.FACE_COOLDOWN_DURATION
            
            # Prepare Record (without sending yet)
            # Upload Image First? Ideally yes, so we have the URL ready
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

            record = {
                "start_time": bj_time.strftime("%Y-%m-%d %H:%M:%S"),
                "face_result": result,
                "person_name": nick_name,
                "event_type": "realtime_identification",
                "confidence": float(conf),
                "user_id": user_id,
                "image_url": image_url
            }

            if is_visitor:
                # Visitor Logic: Buffer it
                with self.state_lock:
                     # If already cooled down, we can CONSIDER buffering
                     if current_time < self.visitor_cooldown_until:
                         return
                
                with self.visitor_buffer_lock:
                    # Update buffer with latest visitor detection
                    # We don't send immediately. We wait.
                    self.pending_visitor_report = (current_time, record)
                    logger.debug(f"Buffered Visitor: {nick_name}, waiting {self.visitor_buffer_duration}s...")
                return

            else:
                # User Logic: Immediate Report + Clear Visitor Buffer
                with self.state_lock:
                    user_unlock_time = self.user_cooldowns.get(user_id, 0.0)
                    if current_time < user_unlock_time:
                        return
                    
                    # It's a valid new User entry
                    self.user_cooldowns[user_id] = current_time + cooldown_duration
                
                # Clear any pending visitor report (Prioritize User)
                with self.visitor_buffer_lock:
                    if self.pending_visitor_report:
                        logger.info("Discarding buffered visitor report due to User detection.")
                        self.pending_visitor_report = None

                logger.info(f"Reporting User: {nick_name} ({user_id})")
                self.save_logs(record)
                self.send_to_agent(record)

        except Exception as e:
            logger.error(f"Async Task Error: {e}")
        finally:
            with self._inflight_lock:
                self._inflight_tasks = max(0, self._inflight_tasks - 1)

    def _cleanup_cooldowns(self, current_time: float):
        """Cleanup expired user cooldowns to save memory."""
        with self.state_lock:
            expired = [uid for uid, ts in self.user_cooldowns.items() if current_time > ts]
            for uid in expired:
                del self.user_cooldowns[uid]

    def _should_ignore_user(self, user_id: str, nick_name: str, user_type: str) -> bool:
        if not user_id or user_id.lower() in ["unknown", "none", ""] or not nick_name:
            return True
        return False

    def recognize(self, frame, timestamp: datetime, suffix="") -> Optional[Dict[str, Any]]:
        try:
            filename = timestamp.strftime(f"%Y%m%d-%H%M%S_face{suffix}.jpg")
            success, encoded_img = cv2.imencode('.jpg', frame)
            
            if not success:
                return None
            
            files = {'file': (filename, encoded_img.tobytes(), 'image/jpeg')}
            headers = {"x-api-key": self.face_api_key}
            params = {
                "limit": 1,
                "det_prob_threshold": 0.8
            }
            
            response = requests.post(
                self.face_api_url, 
                headers=headers,
                files=files, 
                params=params,
                timeout=10
            )
            
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
            img_url = record.get('image_url', '无')
            
            user_id = "Unknown"
            nick_name = record.get('person_name', 'Unknown')
            user_id = record.get('user_id', 'Unknown')

            api_url = Config.AGENT_WORKFLOW_URL
            headers = {
                "X-API-Key": Config.AGENT_API_KEY,
                "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
                "Content-Type": "application/json",
                "Connection": "keep-alive"
            }

            inputs = {
                "device_id": "1",
                "zone": "小仓库",
                "image_url": img_url,
                "person_id": str(user_id)
            }

            payload = {
                "workflowId": Config.AGENT_WORKFLOW_ID,
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
                    f"Message: {resp_data.get("data", {}).get("message", "No message")}\n"
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

    def save_logs(self, record: Dict[str, Any]):
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
    model_path = os.path.join(Config.PROJECT_ROOT, "models", "efficientdet_lite0.tflite")
    
    if not os.path.exists(model_path):
        logger.error(f"Model not found at {model_path}. Please check the path.")
        sys.exit(1)
        
    logger.info(f"Starting FaceCapture (Simplified) with model: {model_path}")
    
    try:
        face_capture = FaceCapture(model_path=model_path)
        face_capture.process()
    except KeyboardInterrupt:
        logger.info("FaceCapture stopped by user.")
    except Exception as e:
        logger.critical(f"FaceCapture crashed: {e}")
