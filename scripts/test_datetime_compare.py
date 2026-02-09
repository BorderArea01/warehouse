from datetime import datetime, timezone, timedelta
import time

# Simulate the setup in AssetScanning.py and TimeCapture.py

# 1. TimeCapture creates start_dt (Aware, UTC+8)
bj_tz = timezone(timedelta(hours=8))
start_dt = datetime.now(bj_tz)
time.sleep(1) # Simulate passage of time

# 2. AssetScanning creates record timestamp (Naive, from time.time())
record_timestamp = time.time()
record_dt_iso = datetime.fromtimestamp(record_timestamp).isoformat()
print(f"Record ISO String: {record_dt_iso}")

# 3. AssetScanning parses record timestamp
rec_time = datetime.fromisoformat(record_dt_iso)
print(f"Parsed Record DT: {rec_time} (tzinfo={rec_time.tzinfo})")
print(f"Start DT: {start_dt} (tzinfo={start_dt.tzinfo})")

# 4. Comparison
try:
    if start_dt <= rec_time:
        print("Comparison Successful: Start <= Record")
    else:
        print("Comparison Successful: Start > Record")
except TypeError as e:
    print(f"Comparison Failed: {e}")
