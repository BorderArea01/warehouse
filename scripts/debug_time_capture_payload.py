import json
import os
import sys
import glob
from datetime import datetime, timedelta

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from src.plugins.ToAgent import ToAgent
except ImportError:
    # Fallback if running directly from plugins folder
    sys.path.append(os.path.join(project_root, 'src', 'plugins'))
    try:
        from ToAgent import ToAgent
    except ImportError:
        print("Warning: Could not import ToAgent")
        ToAgent = None

def get_latest_log_record():
    """
    Finds the latest JSONL log file and reads the last record.
    """
    log_dir = os.path.join(project_root, 'logs', 'person')
    if not os.path.exists(log_dir):
        print(f"[Debug] Log directory not found: {log_dir}")
        return None

    # Get all .jsonl files sorted by modification time (newest first)
    list_of_files = glob.glob(os.path.join(log_dir, '*.jsonl'))
    if not list_of_files:
        print("[Debug] No .jsonl log files found.")
        return None
    
    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"[Debug] Reading from latest log file: {latest_file}")
    
    last_line = None
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            # Read all lines is okay for small log files, 
            # for huge files seek would be better but this is sufficient for debug.
            lines = f.readlines()
            if lines:
                # Filter for valid json lines
                for line in reversed(lines):
                    if line.strip():
                        last_line = line
                        break
    except Exception as e:
        print(f"[Debug] Error reading file: {e}")
        return None
        
    if last_line:
        try:
            return json.loads(last_line)
        except json.JSONDecodeError:
            print("[Debug] Last line is not valid JSON.")
            return None
    return None

def debug_payload_generation():
    print("==========================================")
    print("   TimeCapture Payload Debugger (Real Data)")
    print("==========================================")

    # 1. 获取真实数据 (Real Data)
    record = get_latest_log_record()
    
    if not record:
        print("[Debug] Could not find any real records. Switching to MOCK data.")
        # Fallback Mock Data
        start_time_dt = datetime.now() - timedelta(minutes=10)
        end_time_dt = datetime.now()
        record = {
            "event_type": "realtime_identification",
            "start_time": start_time_dt.isoformat(),
            "face_result": {
                "code": 200,
                "data": {
                    "userId": "MOCK_USER",
                    "nickName": "模拟用户"
                },
                "msg": "success"
            },
            "yolo_confidence": 0.88,
            "end_time": end_time_dt.isoformat()
        }
    else:
        print("[Debug] Successfully loaded latest record from logs.")

    print(f"[Debug] Record Content:\n{json.dumps(record, indent=2, ensure_ascii=False)}\n")

    # 2. 执行格式化逻辑 (Logic from TimeCapture.py)
    start_t = record.get('start_time')
    end_t = record.get('end_time')
    
    # If end_time is missing (e.g. still in progress), use current time for debug
    if not end_t:
        print("[Debug] Record has no end_time. Using current time.")
        end_t = datetime.now().isoformat()
        
    face_res = record.get('face_result', {})
    yolo_conf = record.get('yolo_confidence', 0.95)
    
    # Format times
    try:
        s_dt = datetime.fromisoformat(start_t)
        e_dt = datetime.fromisoformat(end_t)
        
        # Format: 16点30分
        start_str = f"{s_dt.hour}点{s_dt.minute:02d}分"
        
        # End time: 17点 (if 00 mins) or 17点05分
        if e_dt.minute == 0:
             end_str = f"{e_dt.hour}点"
        else:
             end_str = f"{e_dt.hour}点{e_dt.minute:02d}分"
             
    except Exception as e:
        print(f"[Debug] Time formatting error: {e}")
        start_str = start_t
        end_str = end_t
    
    # Extract Identity Info
    user_id = "Unknown"
    nick_name = "Unknown"
    
    if isinstance(face_res, dict) and face_res.get("code") == 200:
         data = face_res.get("data", {})
         user_id = data.get("userId", "Unknown")
         nick_name = data.get("nickName", "Unknown")

    # Construct Query
    query = (
        f"记录人员进出流水：开始时间 {start_str}，结束时间 {end_str} ，"
        f"user_id为：{user_id} ，名称：{nick_name}，"
        f"置信度{yolo_conf:.2f}，device_id: 1。区域是：小仓库。"
    )
    
    print("------------------------------------------")
    print("Generated Query (Sent to Server):")
    print(f"'{query}'")
    print("------------------------------------------")

    # 3. 模拟发送 (Simulate Sending)
    if ToAgent:
        print("\n[Debug] Ready to send to server...")
        to_agent = ToAgent()
        
        # 打印完整的 HTTP Payload (模拟 ToAgent 内部行为)
        payload = {
            "employeeId": to_agent.employee_id,
            "userId": to_agent.user_id,
            "query": query,
            "business_params": {"additionalProp1": {}},
        }
        print(f"[Debug] Full HTTP JSON Payload:\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
        print(f"[Debug] Target URL: {to_agent.base_url}")
        
        confirm = input("\nDo you want to actually send this request to the server? (y/n): ")
        if confirm.lower() == 'y':
            print("[Debug] Sending...")
            try:
                response = to_agent.invoke(query=query)
                print(f"[Debug] Server Response: {response}")
            except Exception as e:
                print(f"[Debug] Error sending: {e}")
        else:
            print("[Debug] Skipped sending.")
    else:
        print("[Debug] ToAgent plugin not found, cannot simulate network request.")

if __name__ == "__main__":
    debug_payload_generation()
