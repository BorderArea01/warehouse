import cv2
import numpy as np
import time
from retinaface import RetinaFace
from collections import defaultdict

# =============================
# 参数配置
# =============================

MIN_FACE_SIZE = 150
BLUR_THRESHOLD = 100
ANGLE_THRESHOLD = 15
IOU_THRESHOLD = 0.4
MAX_MISSING_FRAMES = 10
SAVE_DIR = "captured_faces"

# =============================
# 工具函数
# =============================

def compute_iou(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2]-box1[0]) * (box1[3]-box1[1])
    area2 = (box2[2]-box2[0]) * (box2[3]-box2[1])
    union = area1 + area2 - inter

    return inter / union if union > 0 else 0


def blur_score(img):
    return cv2.Laplacian(img, cv2.CV_64F).var()


def angle_score(landmarks):
    left_eye = landmarks["left_eye"]
    right_eye = landmarks["right_eye"]

    dx = right_eye[0] - left_eye[0]
    dy = right_eye[1] - left_eye[1]

    return np.degrees(np.arctan2(dy, dx))


def evaluate_face(face_img, landmarks):
    h, w = face_img.shape[:2]
    if w < MIN_FACE_SIZE:
        return 0

    blur = blur_score(face_img)
    if blur < BLUR_THRESHOLD:
        return 0

    angle = abs(angle_score(landmarks))
    if angle > ANGLE_THRESHOLD:
        return 0

    brightness = np.mean(face_img)
    if brightness < 60 or brightness > 200:
        return 0

    # 综合评分（你可以调权重）
    return blur


# =============================
# 主程序
# =============================

cap = cv2.VideoCapture(0)

tracks = {}
next_track_id = 0

frame_index = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_index += 1
    detections = []

    faces = RetinaFace.detect_faces(frame)

    if isinstance(faces, dict):
        for key in faces:
            face = faces[key]
            bbox = face["facial_area"]
            landmarks = face["landmarks"]
            detections.append((bbox, landmarks))

    # =============================
    # 简易IOU跟踪
    # =============================

    updated_tracks = {}

    for bbox, landmarks in detections:
        matched_id = None
        max_iou = 0

        for track_id in tracks:
            iou = compute_iou(bbox, tracks[track_id]["bbox"])
            if iou > IOU_THRESHOLD and iou > max_iou:
                max_iou = iou
                matched_id = track_id

        if matched_id is None:
            matched_id = next_track_id
            next_track_id += 1

        x1, y1, x2, y2 = bbox
        face_img = frame[y1:y2, x1:x2]

        score = evaluate_face(face_img, landmarks)

        if matched_id not in tracks:
            tracks[matched_id] = {
                "bbox": bbox,
                "buffer": [],
                "last_seen": frame_index
            }

        tracks[matched_id]["bbox"] = bbox
        tracks[matched_id]["last_seen"] = frame_index

        if score > 0:
            tracks[matched_id]["buffer"].append((score, face_img.copy()))

        updated_tracks[matched_id] = tracks[matched_id]

    # =============================
    # 检查消失的人
    # =============================

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

    # 显示检测框
    for track_id in tracks:
        x1, y1, x2, y2 = tracks[track_id]["bbox"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
        cv2.putText(frame, f"ID {track_id}", (x1, y1-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

    cv2.imshow("Warehouse Capture", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()