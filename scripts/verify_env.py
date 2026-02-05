import cv2
import torch
import sys
import os

print("--- Environment Verification ---")

# 1. Verify Ultralytics/YOLOv5 Dependency
print("\n[1] Checking YOLOv5/Ultralytics...")
try:
    # Try loading the model as the app does
    model = torch.hub.load('ultralytics/yolov5', 'yolov5n', pretrained=True)
    print("SUCCESS: YOLOv5 model loaded successfully.")
except Exception as e:
    print(f"FAIL: Error loading YOLOv5 model: {e}")

# 2. Verify Camera Access
print("\n[2] Checking Camera Access (/dev/video0)...")
try:
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        print("SUCCESS: Camera 0 opened successfully.")
        ret, frame = cap.read()
        if ret:
            print(f"SUCCESS: Captured frame of shape {frame.shape}")
        else:
            print("WARNING: Camera opened but failed to read frame.")
        cap.release()
    else:
        print("FAIL: Could not open Camera 0.")
except Exception as e:
    print(f"FAIL: Exception accessing camera: {e}")

print("\n--- Verification Complete ---")
