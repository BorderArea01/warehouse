
import sys
import os
import time
import signal
import threading

# Add project root to sys.path to ensure we can import from src
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from src.plugins.FaceCapture import FaceCapture
    from src.plugins.TimeCapture import TimeCapture
except ImportError as e:
    print(f"Error importing plugins: {e}")
    print("Ensure you are running from the project root or src folder.")
    sys.exit(1)

def main():
    print("==========================================")
    print("   Warehouse Monitoring System v1.0")
    print("   - FaceCapture (Entry & ID)")
    print("   - TimeCapture (Exit Monitoring)")
    print("==========================================")
    
    # 1. Initialize Services
    try:
        time_capture = TimeCapture()
        face_capture = FaceCapture()
    except Exception as e:
        print(f"Error initializing services: {e}")
        return

    # 2. Start Background Services (TimeCapture)
    # TimeCapture runs in its own daemon thread
    print("[Main] Launching TimeCapture Service...")
    time_capture.start_monitoring()
    
    # 3. Start Foreground Service (FaceCapture)
    # FaceCapture runs in the main thread (Blocking) to handle OpenCV UI events properly
    print("[Main] Launching FaceCapture Service (Foreground)...")
    print("[Main] Press Ctrl+C or 'q' in the window to exit.")
    
    try:
        # This will block until the user quits FaceCapture
        face_capture.start_monitoring()
    except KeyboardInterrupt:
        print("\n[Main] KeyboardInterrupt received. Shutting down...")
    except Exception as e:
        print(f"\n[Main] Unexpected error in FaceCapture: {e}")
    finally:
        # 4. Graceful Shutdown
        print("[Main] Stopping Background Services...")
        time_capture.stop_monitoring()
        print("[Main] System Shutdown Complete.")

if __name__ == "__main__":
    main()
