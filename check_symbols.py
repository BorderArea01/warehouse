import ctypes
import os

try:
    lib_path = "./lib/libModuleAPI.so"
    lib = ctypes.CDLL(lib_path)
    
    print("Library loaded successfully.")
    
    try:
        # Check for SetReadPower
        if hasattr(lib, 'SetReadPower'):
            print("Found SetReadPower")
            print(f"SetReadPower address: {lib.SetReadPower}")
        else:
            print("SetReadPower NOT found")
            
        # Check for SetWritePower
        if hasattr(lib, 'SetWritePower'):
            print("Found SetWritePower")
            print(f"SetWritePower address: {lib.SetWritePower}")
        else:
            print("SetWritePower NOT found")
            
    except Exception as e:
        print(f"Error checking symbols: {e}")

except Exception as e:
    print(f"Failed to load library: {e}")
