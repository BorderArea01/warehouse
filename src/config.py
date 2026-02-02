import os

# 基础路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据库配置
DB_PATH = os.path.join(BASE_DIR, 'data', 'warehouse.db')

# 图片存储配置
IMAGE_DIR = os.path.join(BASE_DIR, 'images')

# 海康威视摄像头配置
HIKVISION_CONFIG = {
    'ip': '192.168.1.64',      # 默认IP，需修改
    'port': 80,                # HTTP端口
    'user': 'admin',           # 默认用户名
    'password': 'password123', # 需修改
    'channel': 1               # 通道号
}

# RFID 配置
RFID_CONFIG = {
    'serial_port': '/dev/ttyUSB0', # 树莓派常见串口
    'baud_rate': 115200,           # 波特率，根据设备说明书修改
    'timeout': 1
}

# 业务配置
SYSTEM_CONFIG = {
    'debounce_seconds': 5,      # RFID防抖时间（秒）
    'snapshot_retain_days': 30  # 图片保留天数
}
