# - 实时监控与人脸检测 ：
# - 程序会打开本地摄像头（Index 0）并保持常开。
# - 使用 YOLOv5n AI 模型实时检测画面中的 人 。
# - 防误触（Debounce） ：只有当人持续出现在画面中超过 0.5秒 时，才会被认定为有效进入，防止光影或飞虫造成的误报。
# - 资源优化逻辑 ：
#   1. 距离过滤 ：仅当检测到的人员在画面中占比超过 8% 时才触发识别，避免处理远处背景路人。
#   2. 频率控制 ：识别请求间隔调整为 1.0秒（原0.3秒），减轻服务器并发压力。
#   3. 智能截断 ：单次进入事件中，同一身份最多上报 3次，随后进入 60秒 冷却期。

# - 自动抓拍与即时上报（连续3次） ：
# - 一旦确认有人进入且满足上述条件，程序会每隔1.0秒截取当前画面（快照）。
# - 内存处理 ：图片直接在内存中编码上传， 完全不写入SD卡 ，保护树莓派硬件。
# - 连续上报 ：为了确保识别成功率，程序会对同一个人连续抓拍并上传 3次 （每次间隔1.0秒）。

# - 多人识别与独立冷却机制 ：
# - 程序支持多人同时或连续进入。
# - 每个人拥有独立的冷却状态（基于人脸识别返回的ID）。
# - 一旦某人的身份被识别并上报达到3次，该用户进入 60秒 的冷却期。
# - 冷却期间，摄像头会继续工作，可以识别并上报画面中的其他新用户，但会自动忽略已冷却的用户。

# - 数据记录与Agent联动 ：
# - 进出记录 ：记录人员进入和离开（超时判定）的精确 北京时间 。
# - Agent通知 ：在人员离开形成完整记录后，自动调用 ToAgent 插件，将完整的人员流水信息（含人脸结果）发送给后端Agent，以便写入数据库。
# - 本地备份 ：同时将记录追加写入到本地的 visit_records.jsonl 文件中作为备份。

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import cv2
import numpy as np
import requests
import json
import os
import sys
import torch
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import concurrent.futures
import threading

# Add project root to sys.path to import ToAgent
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

try:
    from src.plugins.ToAgent import ToAgent
except ImportError:
    # Fallback if running directly from plugins folder
    sys.path.append(os.path.join(project_root, 'src', 'plugins'))
    try:
        from ToAgent import ToAgent
    except ImportError:
        print("Warning: Could not import ToAgent")
        ToAgent = None

class FaceCapture:
    def __init__(self):
        self.face_api_url = "http://192.168.11.24:8088/system/visitorRecord/recognizeFace"
        self.bj_tz = timezone(timedelta(hours=8))
        self.to_agent = ToAgent() if ToAgent else None
        
        # Detection Config
        self.confidence_threshold = 0.6
        self.min_detection_duration = 0.25 # Reduced from 0.5 to 0.25 for faster response
        self.min_face_area_ratio = 0.08 # New: Filter small faces (8% of frame)
        self.headless = os.environ.get('HEADLESS', 'False').lower() == 'true'
        
        # Real-time Reporting Config
        self.max_report_count = 2  # Max times to report per session
        self.cooldown_duration = 60.0 # Seconds to wait after confirming identity
        self.report_interval = 0.3 # Reduced from 1.0 to 0.3 for rapid burst reporting
        
        # Multi-person Tracking State
        self.identified_cooldowns: Dict[str, float] = {} # {user_id_or_name: timestamp}
        self.state_lock = threading.Lock() # Lock for thread-safe state updates
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5) # Thread pool for async uploads
        
        self.cap = None
        self.model = None

    def get_bj_time(self) -> datetime:
        """Returns current time in Beijing Timezone."""
        return datetime.now(self.bj_tz)

    def load_model(self):
        print("[FaceCapture] Loading YOLOv5n model...")
        try:
            # Load model from torch hub
            self.model = torch.hub.load('ultralytics/yolov5', 'yolov5n', pretrained=True)
            self.model.classes = [0]  # Filter to 'person' class
        except Exception as e:
            print(f"[FaceCapture] Error loading model: {e}")
            sys.exit(1)

    def start_monitoring(self):
        """
        Starts the continuous monitoring loop.
        1. Opens camera.
        2. Detects people.
        3. Manages entry/exit events.
        """
        print("[FaceCapture] Starting Monitoring Service...")
        
        # Initialize Camera (Persistent)
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("[FaceCapture] Error: Could not open camera 0.")
            return

        # Check if running in a headless environment
        if not self.headless:
            # Check for DISPLAY environment variable first to avoid Qt core dumps
            if not os.environ.get('DISPLAY'):
                print("[FaceCapture] No DISPLAY environment variable detected. Switching to HEADLESS mode.")
                self.headless = True
            else:
                try:
                    # Try to open a test window to check if display is available
                    # If this fails (e.g. Qt error), we switch to headless mode
                    cv2.imshow("Test", np.zeros((10, 10, 3), dtype=np.uint8))
                    cv2.destroyWindow("Test")
                except Exception as e:
                    print(f"[FaceCapture] Display not available ({e}). Switching to HEADLESS mode.")
                    self.headless = True


        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # Load AI Model
        if self.model is None:
            self.load_model()
            
        print(f"[FaceCapture] Camera and Model Ready. Monitoring...")

        # State Variables
        is_tracking = False
        self.session_report_count = 0 # Counter for uploads in current visual session
        session_start_time = None
        last_seen_time = 0
        
        # Debounce
        potential_start_time = 0
        is_potential_entry = False
        tracking_timeout = 5.0

        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    print("Failed to grab frame")
                    continue

                current_time = datetime.now().timestamp()
                
                # Cleanup old cooldowns
                expired_users = [uid for uid, ts in self.identified_cooldowns.items() if current_time > ts]
                for uid in expired_users:
                    del self.identified_cooldowns[uid]

                # Inference
                results = self.model(frame)
                detections = results.xyxy[0].cpu().numpy()
                
                person_detected_now = False
                valid_detections = [] # Store (x1,y1,x2,y2) for later processing
                frame_area = float(frame.shape[0] * frame.shape[1])

                for *xyxy, conf, cls in detections:
                    if conf >= self.confidence_threshold and int(cls) == 0:
                        x1, y1, x2, y2 = map(int, xyxy)
                        
                        # Filter by area (Optimization)
                        box_area = (x2 - x1) * (y2 - y1)
                        if box_area / frame_area < self.min_face_area_ratio:
                             if not self.headless:
                                 # Draw grey box for ignored people (too far)
                                 cv2.rectangle(frame, (x1, y1), (x2, y2), (100, 100, 100), 1)
                             continue

                        person_detected_now = True
                        valid_detections.append((x1, y1, x2, y2, float(conf)))
                        if not self.headless:
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                
                # --- State Machine ---
                
                if person_detected_now:
                    last_seen_time = current_time
                    
                    if not is_tracking:
                        if not is_potential_entry:
                            is_potential_entry = True
                            potential_start_time = current_time
                        else:
                            if current_time - potential_start_time >= self.min_detection_duration:
                                # Confirmed Entry (of SOMEONE)
                                is_tracking = True
                                self.session_report_count = 0 # Reset counter for new session
                                is_potential_entry = False
                                session_start_time = self.get_bj_time()
                                
                                # Process Frame immediately
                                self.process_frame_for_identities(frame, current_time, detections=valid_detections)
                                self.session_report_count += 1

                    else:
                            # Already tracking
                            # Try to recognize faces periodically
                            # To catch NEW people entering the frame
                            if not hasattr(self, 'last_scene_recognition_time'):
                                 self.last_scene_recognition_time = 0
                            
                            if current_time - self.last_scene_recognition_time >= self.report_interval:
                                 # Smart Truncation: Only report first N times per visual session
                                 if self.session_report_count < self.max_report_count:
                                     self.process_frame_for_identities(frame, current_time, detections=valid_detections)
                                     self.last_scene_recognition_time = current_time
                                     self.session_report_count += 1
                                 else:
                                     # Optional: Log that we are skipping upload to save resources
                                     # print(f"[FaceCapture] Skipping upload. Session limit reached ({self.session_report_count}/{self.max_report_count})")
                                     pass
                        
                else:
                    if is_potential_entry:
                        is_potential_entry = False
                        
                    if is_tracking:
                        if current_time - last_seen_time > tracking_timeout:
                            # Exit
                            print(f"[FaceCapture] Timeout. Ending Session started at {session_start_time}")
                            # For multi-person, "Session" is vague. We just mark the end of activity.
                            # The individual records are sent via process_frame_for_identities.
                            # We can send a summary or just close.
                            is_tracking = False

                if not self.headless:
                    # Overlay cooldown info
                    y_off = 30
                    for uid, ts in self.identified_cooldowns.items():
                         rem = int(ts - current_time)
                         cv2.putText(frame, f"Cooldown {uid}: {rem}s", (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                         y_off += 20
                         
                    cv2.imshow('FaceCapture Monitor', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                        
        except KeyboardInterrupt:
            print("\nStopping monitoring...")
        finally:
            if self.cap:
                self.cap.release()
            cv2.destroyAllWindows()

    def process_frame_for_identities(self, frame, current_time, detections=None):
        """
        Captures face, sends to API, checks identity against cooldowns.
        Supports multi-person detection by cropping and uploading individually.
        Uses ThreadPoolExecutor for asynchronous processing to meet <1s requirement.
        """
        bj_time = self.get_bj_time()
        
        # If no specific detections provided (e.g. legacy call or manual trigger), use full frame
        # But for multi-person support, we strongly prefer passing detections.
        
        targets_to_process = []
        
        if detections is not None and len(detections) > 0:
            # Crop each person
            h, w, _ = frame.shape
            for det in detections:
                if len(det) >= 4:
                    x1, y1, x2, y2 = det[:4]
                    conf = det[4] if len(det) > 4 else 0.0
                
                # Add padding (10%) to ensure face is included and context is preserved
                pad_x = int((x2 - x1) * 0.1)
                pad_y = int((y2 - y1) * 0.1)
                
                crop_x1 = max(0, x1 - pad_x)
                crop_y1 = max(0, y1 - pad_y)
                crop_x2 = min(w, x2 + pad_x)
                crop_y2 = min(h, y2 + pad_y)
                
                crop_img = frame[crop_y1:crop_y2, crop_x1:crop_x2]
                if crop_img.size > 0:
                    # Make a copy to be thread-safe as frame might change
                    targets_to_process.append((crop_img.copy(), conf))
        else:
            # Fallback: Process full frame (Legacy behavior, prone to single-person only)
            targets_to_process.append((frame.copy(), 0.0))

        print(f"[FaceCapture] Async processing {len(targets_to_process)} target(s)...")

        for img_idx, (img_to_send, conf) in enumerate(targets_to_process):
            # Submit to thread pool
            self.executor.submit(self._async_recognize_task, img_to_send, current_time, bj_time, img_idx, conf)

    def _async_recognize_task(self, img_to_send, current_time, bj_time, img_idx, conf=0.0):
        """
        Task to be run in thread pool. Handles recognition and state update.
        """
        try:
            # 1. Capture & Recognize
            result = self.capture_and_recognize(img_to_send, bj_time, suffix=f"_{img_idx}")
            
            if not result:
                return

            # 2. Extract Identity
            user_id = "unknown"
            nick_name = "Unknown"
            
            if isinstance(result, dict) and result.get("code") == 200:
                data = result.get("data", {})
                if data:
                        user_id = str(data.get("userId", "unknown"))
                        nick_name = data.get("nickName", "Unknown")
            
            # 3. Check Cooldown (Thread-safe read)
            # Note: We read without lock for performance, strictly correct would be with lock.
            # But stale read here just means one extra report, which is acceptable.
            with self.state_lock:
                 in_cooldown = user_id in self.identified_cooldowns
            
            if in_cooldown:
                print(f"[FaceCapture] User {nick_name} ({user_id}) is in cooldown. Skipping report.")
                return 

            # 4. Check User Type (Filter Visitors & Unknown)
            user_type = "Unknown"
            user_id_str = str(user_id)
            if isinstance(result, dict) and result.get("code") == 200:
                    data = result.get("data", {})
                    user_type = data.get("userType", "Unknown")
            
            if "游客" in user_type or "visitor" in user_type.lower():
                    print(f"[FaceCapture] Ignored Visitor: {nick_name} ({user_type})")
                    return

            if not user_id_str or user_id_str.lower() in ["unknown", "none", ""] or not nick_name:
                    print(f"[FaceCapture] Ignored Unknown User (ID: {user_id}, Name: {nick_name})")
                    return
                
            # 5. Valid Report
            print(f"[FaceCapture] Recognized: {nick_name} ({user_id}). Reporting...")
            
            # Update State (Thread-safe write)
            with self.state_lock:
                 self.handle_person_state(user_id, nick_name, current_time, result, bj_time, conf)
        
        except Exception as e:
            print(f"[FaceCapture] Async Task Error: {e}")



    def handle_person_state(self, user_id, nick_name, current_time, face_result, bj_time, conf=0.0):
        if not hasattr(self, 'person_states'):
            self.person_states = {} # {uid: {'count': 0, 'cooldown_until': 0}}
            
        state = self.person_states.get(user_id, {'count': 0, 'cooldown_until': 0})
        
        # Check Cooldown
        if current_time < state['cooldown_until']:
            print(f"[FaceCapture] {nick_name} in cooldown. Ignore.")
            return

        # Increment Report Count
        state['count'] += 1
        print(f"[FaceCapture] Reporting {nick_name} ({state['count']}/{self.max_report_count})")
        
        # Send Data
        record = {
            "start_time": bj_time.isoformat(),
            "face_result": face_result,
            "person_name": nick_name,
            "event_type": "realtime_identification",
            "yolo_confidence": float(conf)
        }
        
        # Only save the first record per session to avoid duplicate logs
        if state['count'] == 1:
            self.save_local_json(record)
        else:
            print(f"[FaceCapture] Skip logging for {nick_name} (Verification #{state['count']})")
        
        # Check Max Count
        if state['count'] >= self.max_report_count:
            print(f"[FaceCapture] {nick_name} reached max reports. Cooling down for {self.cooldown_duration}s.")
            state['cooldown_until'] = current_time + self.cooldown_duration
            state['count'] = 0 # Reset count for after cooldown
            
        self.person_states[user_id] = state

    def capture_and_recognize(self, frame, timestamp: datetime, suffix="") -> Optional[Dict[str, Any]]:
        """
        Encodes the frame and sends it to the face recognition API.
        """
        try:
            filename = timestamp.strftime(f"%Y%m%d-%H%M%S_face{suffix}.jpg")
            
            # Encode image to memory
            success, encoded_img = cv2.imencode('.jpg', frame)
            if not success:
                print("Error: Failed to encode image.")
                return None
            
            img_bytes = encoded_img.tobytes()
            
            # Send to API
            print(f"Sending face image {filename} to API...")
            files = {
                'file': (filename, img_bytes, 'image/jpeg')
            }
            
            response = requests.post(self.face_api_url, files=files, timeout=30)
            print(f"Face API Status: {response.status_code}")
            
            try:
                result = response.json()
                print(f"Face API Result: {result}")
                return result
            except:
                print(f"Face API Raw Response: {response.text}")
                return {"raw": response.text}
                
        except Exception as e:
            print(f"Error in capture_and_recognize: {e}")
            return None

    def process_entry_event(self, frame=None):
        """
        Handles the event when a person enters.
        1. Captures face and recognizes it.
        2. Logs start time (Beijing Time).
        3. Returns the partial record.
        """
        start_time = self.get_bj_time()
        print(f"[FaceCapture] Person Detected at {start_time}")
        
        # If no frame provided, capture from camera
        if frame is None:
            print("[FaceCapture] No frame provided, capturing snapshot from local camera...")
            frame = self.capture_snapshot()
            
        if frame is None:
             print("[FaceCapture] Warning: Could not capture frame. Skipping face recognition.")
             face_result = {"error": "Camera capture failed"}
        else:
             # Recognize face
             face_result = self.capture_and_recognize(frame, start_time)
        
        return {
            "start_time": start_time.isoformat(),
            "face_result": face_result
        }

    def capture_snapshot(self):
        """
        Captures a single frame from the local camera (Index 0).
        """
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("[FaceCapture] Error: Could not open camera 0.")
                return None
            
            # Warmup? Sometimes first frame is black
            # cap.read() 
            
            ret, frame = cap.read()
            cap.release()
            
            if not ret:
                print("[FaceCapture] Error: Failed to read frame from camera.")
                return None
                
            return frame
        except Exception as e:
            print(f"[FaceCapture] Error in capture_snapshot: {e}")
            return None

    def process_exit_event(self, start_record: Dict[str, Any]):
        """
        Handles the event when a person leaves.
        1. Logs end time (Beijing Time).
        2. Combines with start record.
        3. Sends complete record to Server/Agent.
        """
        if not start_record:
            return

        end_time = self.get_bj_time()
        start_time_dt = datetime.fromisoformat(start_record["start_time"])
        duration = (end_time - start_time_dt).total_seconds()
        
        complete_record = {
            **start_record,
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "device": "raspberry_pi_5_camera"
        }
        
        print(f"[FaceCapture] Person Left at {end_time}. Duration: {duration}s")
        print(f"[FaceCapture] Complete Record: {json.dumps(complete_record, ensure_ascii=False)}")
        
        # Save locally as backup
        self.save_local_json(complete_record)
        

    def save_local_json(self, record):
        try:
            # Daily Log File
            today_str = datetime.now().strftime("%Y-%m-%d")
            log_dir = os.path.join(project_root, 'logs', 'person')
            os.makedirs(log_dir, exist_ok=True)
            
            file_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")
            
            # Remove redundant field
            if 'person_name' in record:
                del record['person_name']
                
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Error saving local JSON: {e}")

# Simple test if run directly
if __name__ == "__main__":
    # Mock capture
    print("Testing FaceCapture plugin...")
    plugin = FaceCapture()
    
    print("Starting Continuous Monitoring...")
    # This will open camera and loop forever until Ctrl+C
    plugin.start_monitoring()
