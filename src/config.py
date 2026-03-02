import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler

# Ensure project root is in sys.path for imports if needed
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_env_file(filepath):
    """Simple .env loader to avoid external dependencies."""
    if not os.path.exists(filepath):
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                
                # Always set from .env to ensure file config is respected
                # if key not in os.environ:
                os.environ[key] = value

# Load .env from project root
load_env_file(os.path.join(PROJECT_ROOT, '.env'))

class Config:
    # Project Paths
    PROJECT_ROOT = PROJECT_ROOT
    LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
    
    # RTSP Configuration
    # Now we expect full URLs in .env to allow easy domain replacement
    RTSP_URL_TIMECAPTURE = os.getenv('RTSP_URL_TIMECAPTURE')
    RTSP_URL_BACKUP_BASE = os.getenv('RTSP_URL_BACKUP_BASE')

    # Face Capture Configuration
    FACE_API_URL = os.getenv('FACE_API_URL')
    FACE_CONFIDENCE_THRESHOLD = float(os.getenv('FACE_CONFIDENCE_THRESHOLD')) if os.getenv('FACE_CONFIDENCE_THRESHOLD') else 0.65
    FACE_MIN_DETECTION_DURATION = float(os.getenv('FACE_MIN_DETECTION_DURATION')) if os.getenv('FACE_MIN_DETECTION_DURATION') else 0.6
    
    # Time Capture Configuration
    TIME_CONFIDENCE_THRESHOLD = float(os.getenv('TIME_CONFIDENCE_THRESHOLD')) if os.getenv('TIME_CONFIDENCE_THRESHOLD') else 0.6
    TIME_PERSON_TIMEOUT = float(os.getenv('TIME_PERSON_TIMEOUT')) if os.getenv('TIME_PERSON_TIMEOUT') else 5.0

    # Agent Configuration
    AGENT_BASE_URL = os.getenv('AGENT_BASE_URL')
    EMPLOYEE_ID = os.getenv('EMPLOYEE_ID')
    USER_ID = os.getenv('USER_ID')

    # MinIO Uploader Configuration
    MINIO_UPLOAD_URL = os.getenv('MINIO_UPLOAD_URL')

    # Asset Scanning Configuration
    RFID_CONN_STR = os.getenv('RFID_CONN_STR')
    # Try to find lib path automatically if not set
    _default_lib = os.path.join(PROJECT_ROOT, 'lib', 'libModuleAPI.so')
    if not os.path.exists(_default_lib):
        _default_lib = '/usr/local/lib/libModuleAPI.so'
    RFID_LIB_PATH = os.getenv('RFID_LIB_PATH', _default_lib)
    
    # Feishu Configuration
    FEISHU_TOKEN = os.getenv('FEISHU_TOKEN')
    FEISHU_EXCEL_FILE = os.getenv('FEISHU_EXCEL_FILE', os.path.join(PROJECT_ROOT, 'scripts', '资产主表，存储资产的基本信息和状态_线上_数据导出 (1).xlsx'))
    FEISHU_TEMP_DIR = os.getenv('FEISHU_TEMP_DIR', os.path.join(PROJECT_ROOT, 'scripts', 'temp_xlsx_extract'))

    @classmethod
    def get_logger(cls, name):
        """Centralized logger configuration."""
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            
            # Stream Handler
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(formatter)
            logger.addHandler(ch)
            
            # File Handler (Timed Rotating)
            os.makedirs(cls.LOG_DIR, exist_ok=True)
            # Use 'app.log' for general logs, or match main_run.log if preferred.
            # Sticking to 'app.log' as a unified log file for all modules.
            fh = TimedRotatingFileHandler(
                os.path.join(cls.LOG_DIR, 'app.log'),
                when='midnight',
                interval=1,
                backupCount=30,
                encoding='utf-8'
            )
            fh.setFormatter(formatter)
            logger.addHandler(fh)
            
        return logger
