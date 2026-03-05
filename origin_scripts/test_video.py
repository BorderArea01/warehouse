import cv2
import numpy as np
import mediapipe as mp
import time
import os

# ==============================
# 配置参数
# ==============================
MIN_FACE_SIZE = 80       # 最小人脸宽度
BLUR_THRESHOLD = 80      # Laplacian 模糊阈值
BRIGHTNESS_MIN = 60
BRIGHTNESS_MAX = 200
ANGLE_THRESHOLD = 15      # 最大允许倾斜角度
SAVE_DIR = "captured_faces"
MAX_MISSING_FRAMES = 10   # 人消失多少帧后保存

os.makedirs(SAVE_DIR, exist_ok=True)

# ==============================
# MediaPipe 初始化
# ==============================
mp_face = mp.solutions.face_detection
face_detector = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5)

# ==============================
# 工具函数
# ==============================
def blur_score(img):
    return cv2.Laplacian(img, cv2.CV_64F).var()

def brightness_score(img):
    return np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))

def angle_score(landmarks, bbox):
    # 用眼睛关键点计算倾斜角度
    if len(landmarks) < 2:
        return 0
    left_eye = landmarks[0]
    right_eye = landmarks[1]
    dx = right_eye[0] - left_eye[0]
    dy = right_eye[1] - left_eye[1]
    angle = np.degrees(np.arctan2(dy, dx))
    return angle

def evaluate_face(face_img, landmarks, bbox):
    h, w = face_img.shape[:2]
    if w < MIN_FACE_SIZE:
        return 0
    blur = blur_score(face_img)
    if blur < BLUR_THRESHOLD:
        return 0
    bright = brightness_score(face_img)
    if bright < BRIGHTNESS_MIN or bright > BRIGHTNESS_MAX:
        return 0
    angle = abs(angle_score(landmarks, bbox))
    if angle > ANGLE_THRESHOLD:
        return 0
    # 综合评分
    score = blur + bright - angle*2
    return score

# ==============================
# 跟踪缓存
# ==============================
tracks = {}
next_track_id = 0
frame_index = 0

cap = cv2.VideoCapture(0)

# ==============================
# 主循环
# ==============================
fps = 0
fps_time = time.time()

while True:
    ret, frame = cap.read()
    if not ret:
        break
    frame_index += 1
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_detector.process(frame_rgb)

    detections = []

    if results.detections:
        for det in results.detections:
            bboxC = det.location_data.relative_bounding_box
            h, w, _ = frame.shape
            x1 = int(bboxC.xmin * w)
            y1 = int(bboxC.ymin * h)
            x2 = int((bboxC.xmin + bboxC.width) * w)
            y2 = int((bboxC.ymin + bboxC.height) * h)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            face_img = frame[y1:y2, x1:x2]

            # MediaPipe 返回关键点
            landmarks = []
            if det.location_data.relative_keypoints:
                for kp in det.location_data.relative_keypoints:
                    landmarks.append((int(kp.x * w), int(kp.y * h)))

            score = evaluate_face(face_img, landmarks, (x1, y1, x2, y2))
            detections.append({"bbox": (x1, y1, x2, y2), "score": score})

    # ==============================
    # 简单 IOU 跟踪
    # ==============================
    updated_tracks = {}
    for det in detections:
        bbox = det["bbox"]
        score = det["score"]
        matched_id = None
        max_iou = 0
        for track_id in tracks:
            tbbox = tracks[track_id]["bbox"]
            # 计算 IOU
            xA = max(bbox[0], tbbox[0])
            yA = max(bbox[1], tbbox[1])
            xB = min(bbox[2], tbbox[2])
            yB = min(bbox[3], tbbox[3])
            interArea = max(0, xB-xA)*max(0, yB-yA)
            boxAArea = (bbox[2]-bbox[0])*(bbox[3]-bbox[1])
            boxBArea = (tbbox[2]-tbbox[0])*(tbbox[3]-tbbox[1])
            iou = interArea / float(boxAArea + boxBArea - interArea)
            if iou > 0.4 and iou > max_iou:
                max_iou = iou
                matched_id = track_id
        if matched_id is None:
            matched_id = next_track_id
            next_track_id += 1

        if matched_id not in tracks:
            tracks[matched_id] = {"bbox": bbox, "buffer": [], "last_seen": frame_index}
        tracks[matched_id]["bbox"] = bbox
        tracks[matched_id]["last_seen"] = frame_index
        if score > 0:
            tracks[matched_id]["buffer"].append((score, frame[bbox[1]:bbox[3], bbox[0]:bbox[2]].copy()))
        updated_tracks[matched_id] = tracks[matched_id]

    # ==============================
    # 保存消失的人脸
    # ==============================
    for track_id in list(tracks.keys()):
        if track_id not in updated_tracks:
            if frame_index - tracks[track_id]["last_seen"] > MAX_MISSING_FRAMES:
                if tracks[track_id]["buffer"]:
                    best = max(tracks[track_id]["buffer"], key=lambda x: x[0])
                    timestamp = int(time.time())
                    filename = f"{SAVE_DIR}/person_{track_id}_{timestamp}.jpg"
                    cv2.imwrite(filename, best[1])
                    print(f"Saved best face for ID {track_id}")
                del tracks[track_id]

    tracks = updated_tracks

    # ==============================
    # 显示
    # ==============================
    for track_id in tracks:
        x1, y1, x2, y2 = tracks[track_id]["bbox"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"ID {track_id}", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

    # FPS 计算
    fps_time_new = time.time()
    fps = 1.0 / (fps_time_new - fps_time)
    fps_time = fps_time_new
    cv2.putText(frame, f"FPS: {fps:.1f}", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 2)

    cv2.imshow("Warehouse Capture", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()