# -*- coding: utf-8 -*-
"""
Face Capture Plugin for Warehouse Monitoring System (MediaPipe Version).
人脸捕获插件 (MediaPipe版本)
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
# Prevent propagation to root logger to avoid duplicate logs when basicConfig is called elsewhere or by default
logger.propagate = False

# ================= Face Capture Service =================

class FaceCapture:
    """
    Service for detecting persons and recognizing faces.
    人脸识别与抓拍服务
    """

    def __init__(self, model_path: str): # 初始化服务
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

        # Frame Queue
        self.frame_queue = queue.Queue(maxsize=3)
        self.stop_event = threading.Event()
        self.capture_thread = None

        # Simple Tracker State
        self.tracked_objects = []  # List of dict: {'bbox': [x1,y1,x2,y2], 'last_seen': time, 'last_api_time': time, 'id': str}
        self.tracker_lock = threading.Lock()
        
        # Load initial state
        self._load_open_user_cache()

    def _init_detector(self): # 初始化 MediaPipe 检测器
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

    def _initialize_camera(self): # 初始化摄像头
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            logger.error("Could not open camera 0.")
            return False
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        
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

    def _capture_loop(self): # 摄像头采集线程
        """Thread function to continuously capture frames."""
        logger.info("Starting Camera Capture Thread...")
        
        # Initialize camera
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
            
            # Put frame to queue, drop oldest if full
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

    def start_monitoring(self): # 启动主监控循环
        """Start the main monitoring loop."""
        logger.debug("Starting FaceCapture Monitoring Service...")
        
        self._init_detector()

        # Start capture thread
        self.stop_event.clear()
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()

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
        
        min_detection_duration = Config.FACE_MIN_DETECTION_DURATION
        # min_face_area_ratio is not in config, using constant logic or hardcoded
        min_face_area_ratio = 0.08
        report_interval = 1.0

        try:
            while True:
                try:
                    # Get frame from queue
                    try:
                        frame = self.frame_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    
                    current_time = time.time()
                    self._cleanup_cooldowns(current_time)

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    
                    detection_result = self.detector.detect(mp_image)
                    detections = detection_result.detections
                    
                    valid_detections = []
                    frame_area = float(frame.shape[0] * frame.shape[1])
                    person_detected_now = False

                    # First pass: collect valid detections
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

                    # Process detections (with CLEAN frame)
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
                                    session_start_time = datetime.now(self.bj_tz)
                                    
                                    self.process_frame(frame, current_time, detections=valid_detections)
                                    session_report_count += 1
                        else:
                            if current_time - last_scene_recognition_time >= report_interval:
                                self.process_frame(frame, current_time, detections=valid_detections)
                                last_scene_recognition_time = current_time
                                session_report_count += 1
                    else:
                        if is_potential_entry:
                            is_potential_entry = False
                            
                        if is_tracking:
                            if current_time - last_seen_time > tracking_timeout:
                                logger.info(f"Session ended. Started at {session_start_time}")
                                is_tracking = False

                    # Second pass: draw debug info (on frame that is now safe to modify)
                    if not self.headless:
                        for det in valid_detections:
                            x1, y1, x2, y2, score = det
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(frame, f"Person {score:.2f}", (x1, y1 - 10), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                                       
                        self._draw_debug_info(frame, current_time)
                        cv2.imshow('FaceCapture Monitor', frame)
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            break
                except Exception as e:
                    logger.error(f"Monitoring Loop Error: {e}")
                    # time.sleep(0.1)
                        
        except KeyboardInterrupt:
            logger.info("Stopping monitoring...")
        finally:
            self.stop_event.set()
            if self.capture_thread:
                self.capture_thread.join(timeout=2.0)
            
            # Double check resource release
            if self.cap:
                self.cap.release()
                self.cap = None

            try:
                self.executor.shutdown(wait=False)
            except Exception:
                pass
            self.detector = None
            cv2.destroyAllWindows()

    def _cleanup_cooldowns(self, current_time: float): # 清理过期的冷却状态
        expired = [uid for uid, ts in self.identified_cooldowns.items() if current_time > ts]
        for uid in expired:
            del self.identified_cooldowns[uid]

    def _draw_debug_info(self, frame, current_time: float): # 绘制调试信息
        y_off = 30
        for uid, ts in self.identified_cooldowns.items():
            rem = int(ts - current_time)
            cv2.putText(frame, f"Cooldown {uid}: {rem}s", (10, y_off), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            y_off += 20

    def _calculate_iou(self, boxA, boxB): # 计算两个框的重叠率 (IOU)
        # determine the (x, y)-coordinates of the intersection rectangle
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        # compute the area of intersection rectangle
        interArea = max(0, xB - xA + 1) * max(0, yB - yA + 1)

        # compute the area of both the prediction and ground-truth rectangles
        boxAArea = (boxA[2] - boxA[0] + 1) * (boxA[3] - boxA[1] + 1)
        boxBArea = (boxB[2] - boxB[0] + 1) * (boxB[3] - boxB[1] + 1)

        # compute the intersection over union by taking the intersection
        # area and dividing it by the sum of prediction + ground-truth
        # areas - the interesection area
        iou = interArea / float(boxAArea + boxBArea - interArea)

        # return the intersection over union value
        return iou

    def _calculate_quality_score(self, bbox, frame_w, frame_h, crop_img=None):
        """
        计算抓拍质量分数 (0.0 - 1.0)
        基于:
        1. 面积占比 (越大越好)
        2. 中心偏移 (越居中越好)
        3. 清晰度 (越清晰越好)
        4. 亮度 (适中最好)
        """
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        
        # 1. 面积分数 (Area Score)
        # 假设人脸/人体占比达到画面 50% 算满分，太小分数低 (稍微放宽一点，因为Laplacian需要像素支撑)
        area = w * h
        frame_area = frame_w * frame_h
        area_ratio = area / frame_area
        area_score = min(1.0, area_ratio / 0.5)
        
        # 2. 中心分数 (Center Score)
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        frame_cx = frame_w / 2
        frame_cy = frame_h / 2
        
        dx = abs(cx - frame_cx) / (frame_w / 2)
        dy = abs(cy - frame_cy) / (frame_h / 2)
        dist = (dx + dy) / 2
        center_score = max(0.0, 1.0 - dist)

        # 3. 图像质量 (Image Quality)
        blur_score = 0.0
        bright_score = 0.0
        
        if crop_img is not None and crop_img.size > 0:
            gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
            
            # 清晰度 (Laplacian Variance)
            # 一般来说 > 100 算清晰，< 50 算模糊
            blur_val = cv2.Laplacian(gray, cv2.CV_64F).var()
            blur_score = min(1.0, max(0.0, (blur_val - 50) / 300))
            
            # 亮度 (Brightness)
            # 理想亮度在 80-180 之间
            mean_val = np.mean(gray)
            if 80 <= mean_val <= 180:
                bright_score = 1.0
            else:
                # 偏离越远分数越低
                if mean_val < 80:
                    bright_score = max(0.0, mean_val / 80)
                else:
                    bright_score = max(0.0, (255 - mean_val) / 75)
        
        # 综合分数: 
        # 面积: 0.4 (保证大小)
        # 中心: 0.1 (位置次要)
        # 清晰度: 0.3 (拒绝模糊)
        # 亮度: 0.2 (拒绝逆光/过暗)
        final_score = (area_score * 0.4) + (center_score * 0.1) + (blur_score * 0.3) + (bright_score * 0.2)
        
        return final_score

    def process_frame(self, frame: np.ndarray, current_time: float, 
                                   detections: List[Tuple] = None): # 处理帧中的人脸: 裁剪、追踪并识别
        """Process detected persons: crop and recognize with tracking."""
        bj_time = datetime.now(self.bj_tz)
        targets_to_process = []
        
        # Tracking config
        iou_threshold = 0.5
        tracking_timeout = 2.0  # Remove object if not seen for 2s
        api_interval = 5.0      # Don't call API for same object within 5s
        
        # Quality capture config
        capture_window = 1.0    # 抓拍窗口期: 1秒
        min_quality_threshold = 0.75 # 立即抓拍的质量阈值
        min_accept_threshold = 0.4 # 最低接受阈值 (如果超时了还没达到这个分，就放弃这次抓拍)
        
        h_frame, w_frame, _ = frame.shape

        # Update tracked objects
        with self.tracker_lock:
            # 1. Clean up stale objects
            self.tracked_objects = [
                obj for obj in self.tracked_objects 
                if current_time - obj['last_seen'] < tracking_timeout
            ]
            
            # 2. Match detections to existing objects
            matched_indices = set()
            
            if detections:
                for det in detections:
                    bbox = det[:4] # x1, y1, x2, y2
                    conf = det[4]
                    
                    best_iou = 0.0
                    best_obj_idx = -1
                    
                    for idx, obj in enumerate(self.tracked_objects):
                        if idx in matched_indices:
                            continue
                        iou = self._calculate_iou(bbox, obj['bbox'])
                        if iou > best_iou:
                            best_iou = iou
                            best_obj_idx = idx
                    
                    # 裁剪图像用于计算质量
                    current_crop = self._crop_image(frame, bbox)
                    quality_score = self._calculate_quality_score(bbox, w_frame, h_frame, current_crop)
                    
                    if best_iou > iou_threshold:
                        # Matched existing object
                        obj = self.tracked_objects[best_obj_idx]
                        obj['bbox'] = bbox
                        obj['last_seen'] = current_time
                        matched_indices.add(best_obj_idx)
                        
                        # Check capture state
                        state = obj.get('state', 'detecting')
                        
                        if state == 'captured':
                            # Already captured, check for re-capture timeout
                            if current_time - obj.get('last_api_time', 0.0) > api_interval:
                                # Reset for re-capture
                                obj['state'] = 'detecting'
                                obj['capture_start_time'] = current_time
                                obj['best_score'] = quality_score
                                obj['best_crop'] = current_crop
                                obj['best_crop_conf'] = conf
                        
                        elif state == 'detecting':
                            # In capture window, update best shot
                            if quality_score > obj.get('best_score', -1.0):
                                obj['best_score'] = quality_score
                                obj['best_crop'] = current_crop
                                obj['best_crop_conf'] = conf
                            
                            time_elapsed = current_time - obj.get('capture_start_time', current_time)
                            
                            # Trigger capture if:
                            # 1. Quality is excellent (immediate capture)
                            # 2. Capture window expired (timeout capture)
                            should_capture = False
                            
                            if quality_score >= min_quality_threshold:
                                should_capture = True
                                logger.info(f"High quality capture triggered (Score: {quality_score:.2f})")
                            elif time_elapsed >= capture_window:
                                best_score_so_far = obj.get('best_score', 0.0)
                                if best_score_so_far >= min_accept_threshold:
                                    should_capture = True
                                    logger.info(f"Capture window expired, using best shot (Score: {best_score_so_far:.2f})")
                                else:
                                    # Quality too low, reset window and keep waiting
                                    # logger.debug(f"Quality too low ({best_score_so_far:.2f}), waiting for better shot...")
                                    obj['capture_start_time'] = current_time # Reset timer
                                    # Don't reset best_score completely, keep trying to beat it
                            
                            if should_capture:
                                best_crop = obj.get('best_crop')
                                best_conf = obj.get('best_crop_conf', conf)
                                
                                if best_crop is not None and best_crop.size > 0:
                                    targets_to_process.append((best_crop, best_conf, best_obj_idx))
                                    obj['state'] = 'captured'
                                    obj['last_api_time'] = current_time
                                    # Clear memory
                                    obj.pop('best_crop', None)

                    else:
                        # New object
                        new_obj = {
                            'bbox': bbox,
                            'last_seen': current_time,
                            'last_api_time': 0.0,
                            'state': 'detecting',
                            'capture_start_time': current_time,
                            'best_score': quality_score,
                            'best_crop': current_crop,
                            'best_crop_conf': conf
                        }
                        self.tracked_objects.append(new_obj)
                        # Don't capture immediately unless quality is super high
                        if quality_score >= min_quality_threshold:
                            targets_to_process.append((new_obj['best_crop'], conf, len(self.tracked_objects)-1))
                            new_obj['state'] = 'captured'
                            new_obj['last_api_time'] = current_time
                            new_obj.pop('best_crop', None)

        if not targets_to_process:
            return

        logger.debug(f"Async processing {len(targets_to_process)} target(s)...")

        for (crop_img, conf, tracker_idx) in targets_to_process:
            if crop_img is None or crop_img.size == 0:
                continue

            with self._inflight_lock:
                if self._inflight_tasks >= self._max_inflight_tasks:
                    continue
                self._inflight_tasks += 1
            
            self.executor.submit(
                self.recognize_task, crop_img.copy(), current_time, bj_time, tracker_idx, conf
            )

    def _crop_image(self, frame, bbox):
        x1, y1, x2, y2 = bbox
        h, w, _ = frame.shape
        
        pad_x = int((x2 - x1) * 0.1)
        pad_y = int((y2 - y1) * 0.1)
        crop_x1 = max(0, x1 - pad_x)
        crop_y1 = max(0, y1 - pad_y)
        crop_x2 = min(w, x2 + pad_x)
        crop_y2 = min(h, y2 + pad_y)
        
        return frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()

    def recognize_task(self, img_to_send, current_time, bj_time, img_idx, conf): # 异步识别任务
        try:
            result = self.recognize(img_to_send, bj_time, suffix=f"_{img_idx}")
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
                return

            with self.state_lock:
                in_cooldown = user_id in self.identified_cooldowns
            
            if in_cooldown:
                return 

            # Check visitor status
            is_visitor = "游客" in nick_name or "visitor" in nick_name.lower() or "游客" in user_type or "visitor" in user_type.lower()
            
            if is_visitor:
                print(f"[Visitor] Detected: {nick_name} ({user_id})")
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

    def _should_ignore_user(self, user_id: str, nick_name: str, user_type: str) -> bool: # 检查是否忽略该用户(无效ID或名字)
        if not user_id or user_id.lower() in ["unknown", "none", ""] or not nick_name:
            return True
            
        return False

    def _update_person_state(self, user_id, nick_name, current_time, face_result, bj_time, conf, image_url="无"): # 更新人员状态(冷却、上报)
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
        
        self.save_logs(record)
        self.send_to_agent(record)
        
        # Add to in-memory cache to avoid reading file next time
        self._open_user_cache.add(str(user_id))
        
        state['cooldown_until'] = current_time + cooldown_duration
        self.identified_cooldowns[user_id] = state['cooldown_until']
        self.person_states[user_id] = state

    def _is_user_already_in(self, user_id: str) -> bool: # 检查用户是否已经在场内 (基于日志文件)
        self._check_day_rollover()
        return str(user_id) in self._open_user_cache

    def _check_day_rollover(self): # 检查日期变更，重置缓存
        today_str = datetime.now().strftime("%Y-%m-%d")
        if self._open_cache_day != today_str:
            self._open_user_cache = set()
            self._open_cache_day = today_str
            self._load_open_user_cache() # Reload for new day (likely empty)

    def _load_open_user_cache(self): # 加载今日已入场用户
        today_str = datetime.now().strftime("%Y-%m-%d")
        self._open_cache_day = today_str
        
        log_dir = os.path.join(Config.PROJECT_ROOT, 'logs', 'person')
        file_path = os.path.join(log_dir, f"{today_str}_visit_records.jsonl")
        
        if not os.path.exists(file_path):
            self._open_user_cache = set()
            return

        logger.info(f"Loading open user cache from {file_path}...")
        open_map = {}
        try:
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
            logger.info(f"Loaded {len(self._open_user_cache)} users currently in warehouse.")
            
        except Exception as e:
            logger.error(f"Error loading open user cache: {e}")
            self._open_user_cache = set()

    def recognize(self, frame, timestamp: datetime, suffix="") -> Optional[Dict[str, Any]]: # 调用人脸识别API
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

    def send_to_agent(self, record: Dict[str, Any]): # 发送数据到 Agent (Workflow)
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

    def save_logs(self, record: Dict[str, Any]): # 保存本地 JSON 日志
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
    # 日志已由 Config.get_logger 配置，无需 basicConfig
    # 只需要确保 logger 正常工作
    
    # 确保模型路径正确
    # 假设模型文件在项目根目录的 models 文件夹下
    model_path = os.path.join(Config.PROJECT_ROOT, "models", "efficientdet_lite0.tflite")
    
    if not os.path.exists(model_path):
        logger.error(f"Model not found at {model_path}. Please check the path.")
        # 尝试使用默认路径或者提示用户下载
        # 这里为了演示，假设用户已经放置了模型文件
        sys.exit(1)
        
    logger.info(f"Starting FaceCapture with model: {model_path}")
    
    try:
        face_capture = FaceCapture(model_path=model_path)
        face_capture.start_monitoring()
    except KeyboardInterrupt:
        logger.info("FaceCapture stopped by user.")
    except Exception as e:
        logger.critical(f"FaceCapture crashed: {e}")

