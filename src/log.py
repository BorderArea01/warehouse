import os
import sys
import logging
from logging.handlers import RotatingFileHandler

_configured = False

def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def setup_logging(level=logging.INFO):
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    log_dir = os.path.join(_project_root(), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(log_dir, 'app.log'), maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    fh.setFormatter(fmt)
    root.addHandler(fh)
    _configured = True

def get_logger(name):
    setup_logging()
    return logging.getLogger(name)
