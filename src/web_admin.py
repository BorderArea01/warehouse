import os
import shutil
import re
import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Warehouse Admin")

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
ENV_FILE = os.path.join(PROJECT_ROOT, '.env')

# Ensure logs directory exists
os.makedirs(LOG_DIR, exist_ok=True)

class ConfigUpdate(BaseModel):
    content: str

def parse_date_from_filename(filename: str, filepath: str) -> str:
    """Extract date from filename or fallback to modification time."""
    # Try YYYY-MM-DD pattern
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    
    # Fallback to file modification time
    try:
        mtime = os.path.getmtime(filepath)
        return datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
    except:
        return "Unknown"

@app.get("/api/logs")
def list_logs():
    """List logs grouped by date."""
    grouped_files: Dict[str, List[Dict[str, Any]]] = {}
    
    print(f"Scanning logs in {LOG_DIR}")
    if os.path.exists(LOG_DIR):
        for root, dirs, filenames in os.walk(LOG_DIR):
            for filename in filenames:
                if filename.startswith('.'): continue # Skip hidden files
                
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, LOG_DIR)
                
                date_str = parse_date_from_filename(filename, full_path)
                
                # Determine file type/category
                category = "System"
                if "asset" in filename.lower() or "asset" in rel_path.lower():
                    category = "Asset"
                elif "visit" in filename.lower() or "person" in rel_path.lower() or "face" in filename.lower():
                    category = "Person"
                
                print(f"Found log: {rel_path} ({category})")
                
                file_info = {
                    "name": filename,
                    "path": rel_path, # Path relative to LOG_DIR, including subdir if any
                    "category": category,
                    "size": os.path.getsize(full_path)
                }
                
                if date_str not in grouped_files:
                    grouped_files[date_str] = []
                grouped_files[date_str].append(file_info)
    
    # Sort dates descending
    sorted_dates = sorted(grouped_files.keys(), reverse=True)
    
    # Construct response
    result = []
    for date in sorted_dates:
        # Sort files within date by category then name
        files = sorted(grouped_files[date], key=lambda x: (x['category'], x['name']))
        result.append({
            "date": date,
            "files": files
        })
        
    return result

@app.get("/api/logs/{file_path:path}")
def get_log(file_path: str, lines: int = 2000):
    # Prevent directory traversal
    safe_path = os.path.normpath(os.path.join(LOG_DIR, file_path))
    if not safe_path.startswith(LOG_DIR) or not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Log file not found or access denied")
    
    try:
        # Read file
        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            # If it's too large, maybe we should truncate? 
            # For now, let's just return it. The frontend can handle a few MBs.
            # If extremely large, we might want to tail it.
            if len(content) > 1024 * 1024 * 5: # 5MB limit for safety
                return {"content": content[-1024*1024*5:], "truncated": True}
            return {"content": content, "truncated": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/logs/{file_path:path}")
def delete_log(file_path: str):
    # Prevent directory traversal
    safe_path = os.path.normpath(os.path.join(LOG_DIR, file_path))
    if not safe_path.startswith(LOG_DIR) or not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Log file not found or access denied")
    
    try:
        os.remove(safe_path)
        return {"status": "success", "message": f"File {file_path} deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config")
def get_config():
    if not os.path.exists(ENV_FILE):
        return {"content": ""}
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        return {"content": f.read()}

@app.post("/api/config")
def update_config(config: ConfigUpdate):
    try:
        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.write(config.content)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/export")
def export_config():
    if not os.path.exists(ENV_FILE):
        raise HTTPException(status_code=404, detail=".env file not found")
    return FileResponse(ENV_FILE, filename=".env", media_type='text/plain')

@app.post("/api/config/import")
async def import_config(file: UploadFile = File(...)):
    try:
        with open(ENV_FILE, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

def main():
    print("Starting Warehouse Admin Interface...")
    port = int(os.environ.get("WEB_ADMIN_PORT", 13999))
    print(f"Access at: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
