import cv2
import json
import os
import sys
from datetime import datetime

# Add current directory to path to import sibling script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from test_face_recognition import recognize_face
except ImportError:
    print("Error: Could not import recognize_face from test_face_recognition.py")
    sys.exit(1)

def main():
    # Initialize Camera
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return

    print("="*50)
    print("FACE CAPTURE & RECOGNITION TOOL")
    print("="*50)
    print("Controls:")
    print("  SPACE: Capture photo and recognize")
    print("  Q:     Quit")
    print("-" * 50)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame")
                break

            # Show preview
            cv2.imshow('Camera Preview - Press SPACE to Capture', frame)

            key = cv2.waitKey(1) & 0xFF
            
            # Quit
            if key == ord('q'):
                break
            
            # Capture
            elif key == ord(' '):
                print("\n[Capturing]...")
                
                # Encode image to jpg bytes
                success, encoded_img = cv2.imencode('.jpg', frame)
                if not success:
                    print("Error: Failed to encode image.")
                    continue
                
                img_bytes = encoded_img.tobytes()
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                filename = f"capture_{timestamp}.jpg"
                
                # 1. Call API
                print(f"Recognizing face for {filename}...")
                result = recognize_face(img_bytes, filename)
                
                if result:
                    # 2. Save JSON
                    json_filename = f"result_{timestamp}.json"
                    try:
                        with open(json_filename, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
                        print(f"Success! Result saved to {json_filename}")
                    except Exception as e:
                        print(f"Error saving JSON: {e}")
                else:
                    print("Failed to get response from API.")
                
                print("-" * 50)
                print("Ready for next capture...")

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Exiting.")

if __name__ == "__main__":
    main()
