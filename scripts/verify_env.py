import sys
import os
import ctypes

def check_cv2():
    try:
        import cv2
        print(f"[OK] cv2 imported. Version: {cv2.__version__}")
        return True
    except ImportError as e:
        print(f"[FAIL] cv2 import failed: {e}")
        return False

def check_mediapipe():
    try:
        import mediapipe
        print(f"[OK] mediapipe imported.")
        return True
    except ImportError as e:
        print(f"[FAIL] mediapipe import failed: {e}")
        return False

def check_rfid_lib():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lib_path = os.path.join(project_root, 'lib', 'libModuleAPI.so')
    
    print(f"Checking RFID lib at: {lib_path}")
    if not os.path.exists(lib_path):
        print(f"[FAIL] Library file not found at {lib_path}")
        return False
        
    try:
        ctypes.CDLL('libstdc++.so.6', mode=ctypes.RTLD_GLOBAL)
        lib = ctypes.CDLL(lib_path)
        print(f"[OK] RFID library loaded successfully.")
        return True
    except OSError as e:
        print(f"[FAIL] Failed to load RFID library: {e}")
        return False

if __name__ == "__main__":
    print("=== Environment Verification ===")
    ok_cv = check_cv2()
    ok_mp = check_mediapipe()
    ok_rfid = check_rfid_lib()
    
    if ok_cv and ok_mp and ok_rfid:
        print("\nAll checks passed!")
        sys.exit(0)
    else:
        print("\nSome checks failed.")
        sys.exit(1)
