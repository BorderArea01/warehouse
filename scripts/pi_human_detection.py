import cv2
import torch
import time
import sys
import os
from datetime import datetime, timezone, timedelta
import numpy as np

# Add the scripts directory to path to import the sibling module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from test_face_recognition import recognize_face
except ImportError:
    print("Warning: Could not import recognize_face from test_face_recognition.py")
    def recognize_face(img_data, filename):
        print(f"Mock send {filename} (module not found)")

# Configuration
CONFIDENCE_THRESHOLD = 0.6  # Increased from 0.5 to reduce false positives
TRACKING_TIMEOUT = 5.0  # Seconds to wait after losing sight of person before ending session
MIN_DETECTION_DURATION = 1.0 # Seconds a person must be detected to count as valid entry (Debounce)

# Check for HEADLESS env var, default to False (show window)
HEADLESS = os.environ.get('HEADLESS', 'False').lower() == 'true'

# RTSP Configuration (For reference / Video Backup)
# Note: Special characters in password must be URL encoded. '@' -> '%40'
# Original: rtsp://admin:Lzwc@2025.@192.168.13.140:554/Streaming/Channels/101
# Encoded:  rtsp://admin:Lzwc%402025.@192.168.13.140:554/Streaming/Channels/101
RTSP_URL_BACKUP = "rtsp://admin:Lzwc%402025.@192.168.13.140:554/Streaming/Channels/101"

# Timezone: Beijing Time (UTC+8)
BJ_TZ = timezone(timedelta(hours=8))

# Storage Configuration
DELETE_PROCESSED_IMAGES = True  # Delete images after processing to save SD card space

def get_bj_time():
    """Returns current time in Beijing Timezone."""
    return datetime.now(BJ_TZ)

def trigger_warehouse_recording(action, timestamp):
    """
    Mock function to trigger warehouse camera recording.
    In production, this might call a DVR API or send a signal.
    """
    print(f"\n[System] TRIGGER: Warehouse Camera {action} Recording at {timestamp}")

def save_local_record(data):
    """
    Saves the visit record locally for later processing.
    """
    print("\n" + "="*50)
    print("SAVING RECORD LOCALLY:")
    print(f"Start Time: {data['start_time']}")
    print(f"End Time:   {data['end_time']}")
    print(f"Image Path: {data.get('image_path', 'N/A')}")
    print(f"Face Result: {data.get('face_result', 'N/A')}")
    print("="*50 + "\n")
    
    # Append to a local JSON lines file
    import json
    try:
        with open('visit_records.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"Error saving local record: {e}")

def load_model():
    print("Loading YOLOv5n model...")
    try:
        # Load model from torch hub
        model = torch.hub.load('ultralytics/yolov5', 'yolov5n', pretrained=True)
        return model
    except Exception as e:
        print(f"Error loading model: {e}")
        sys.exit(1)

def main():
    # Initialize Camera
    # Use Local Camera (Index 0) for Face Capture & Detection
    print(f"Connecting to Local Camera (Index 0)...")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print(f"Error: Cannot open Local Camera. Trying Index 1...")
        cap = cv2.VideoCapture(1)
        if not cap.isOpened():
            print("Error: Cannot open any camera.")
            return

    # Set camera resolution (RTSP streams usually ignore this, but good practice)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    model = load_model()
    model.classes = [0]  # Filter to 'person' class

    print(f"Starting detection loop. Headless mode: {HEADLESS}")
    
    # Session State
    is_tracking = False
    session_start_time = None
    last_seen_time = 0
    best_frame = None
    max_confidence_seen = 0.0
    
    # Debounce State
    potential_start_time = 0
    is_potential_entry = False

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame (stream ended or network issue?)")
                time.sleep(1)
                continue
            
            # Inference
            results = model(frame)
            detections = results.xyxy[0].cpu().numpy()
            
            person_detected_now = False
            current_max_conf = 0.0
            
            # Check for persons in current frame
            for *xyxy, conf, cls in detections:
                if conf >= CONFIDENCE_THRESHOLD and int(cls) == 0:
                    person_detected_now = True
                    current_max_conf = max(current_max_conf, conf)
                    
                    x1, y1, x2, y2 = map(int, xyxy)
                    if not HEADLESS:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"Person {conf:.2f}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            current_time = time.time()

            # --- State Machine Logic ---
            
            if person_detected_now:
                last_seen_time = current_time
                
                # Check logic for STARTING a session
                if not is_tracking:
                    if not is_potential_entry:
                        # First frame of potential person
                        is_potential_entry = True
                        potential_start_time = current_time
                    else:
                        # Continue potential entry
                        duration = current_time - potential_start_time
                        if duration >= MIN_DETECTION_DURATION:
                            # Confirmed Entry!
                            is_tracking = True
                            is_potential_entry = False # Reset debounce
                            
                            session_start_time = get_bj_time()
                            print(f"\n[Event] Person Entered at {session_start_time}. Starting Tracking...")
                            trigger_warehouse_recording("START", session_start_time)
                            
                            max_confidence_seen = 0.0
                            best_frame = None

                # UPDATE SESSION (Keep the best frame)
                # Only update if we are officially tracking
                if is_tracking and current_max_conf > max_confidence_seen:
                    max_confidence_seen = current_max_conf
                    best_frame = frame.copy()

            else:
                # No person detected right now
                
                # Reset debounce if detection breaks before confirmation
                if is_potential_entry:
                    is_potential_entry = False
                    
                if is_tracking:
                    # Check if timeout exceeded
                    if current_time - last_seen_time > TRACKING_TIMEOUT:
                        # END SESSION
                        session_end_time = get_bj_time()
                        print(f"[Event] Person Left at {session_end_time} (Timeout > {TRACKING_TIMEOUT}s). Finalizing Session...")
                        trigger_warehouse_recording("STOP", session_end_time)
                        
                        # 1. Recognize Face using the best frame collected
                        face_result = None
                        image_path = None
                        
                        if best_frame is not None:
                            # Save image locally first
                            images_dir = "captured_images"
                            if not os.path.exists(images_dir):
                                os.makedirs(images_dir)
                            
                            filename = session_end_time.strftime("%Y%m%d-%H%M%S_best.jpg")
                            image_path = os.path.join(images_dir, filename)
                            
                            try:
                                cv2.imwrite(image_path, best_frame)
                                print(f"  > Saved best frame to: {image_path}")
                                
                                # Read it back or use encoded bytes for API
                                with open(image_path, 'rb') as f:
                                    img_bytes = f.read()
                                    
                                print("  > Sending to Face Recognition API...")
                                face_result = recognize_face(img_bytes, filename)
                                
                            except Exception as e:
                                print(f"  > Error saving/sending image: {e}")
                        else:
                            print("  > Warning: No valid frame captured during session.")

                        # 2. Save/Return Data
                        record = {
                            "start_time": session_start_time.isoformat(),
                            "end_time": session_end_time.isoformat(),
                            "duration_seconds": (session_end_time - session_start_time).total_seconds(),
                            "image_path": image_path,
                            "face_result": face_result
                        }
                        save_local_record(record)

                        # 3. Cleanup Image if enabled
                        if DELETE_PROCESSED_IMAGES and image_path and os.path.exists(image_path):
                            try:
                                os.remove(image_path)
                                print(f"  > [Cleanup] Deleted local image: {image_path}")
                                # Update record to reflect deletion? 
                                # Maybe keep the path in record so we know it WAS there, or remove it.
                                # The user wants 'personnel flow info', so the metadata is key.
                            except Exception as e:
                                print(f"  > [Cleanup] Error deleting image: {e}")
                        
                        # Reset State
                        is_tracking = False
                        best_frame = None
                        session_start_time = None

            # --- Display ---
            if not HEADLESS:
                status = "TRACKING" if is_tracking else "IDLE"
                color = (0, 0, 255) if is_tracking else (200, 200, 200)
                cv2.putText(frame, f"Status: {status}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
                
                cv2.imshow('YOLOv5 Human Detection', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                    
    except KeyboardInterrupt:
        print("\nStopping by user request...")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        cap.release()
        if not HEADLESS:
            cv2.destroyAllWindows()
        print("Camera released. Exiting.")

if __name__ == "__main__":
    main()
