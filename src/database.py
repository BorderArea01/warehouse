import sqlite3
import os
from .config import DB_PATH
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def add_asset(self, rfid_code, name, model, spec, category):
        """添加新资产"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO assets (rfid_code, name, model, spec, category)
                VALUES (?, ?, ?, ?, ?)
            ''', (rfid_code, name, model, spec, category))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            print(f"Asset with RFID {rfid_code} already exists.")
            return None
        finally:
            conn.close()

    def get_asset_by_rfid(self, rfid_code):
        """根据RFID查询资产信息"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM assets WHERE rfid_code = ?', (rfid_code,))
        result = cursor.fetchone()
        conn.close()
        return result

    def log_access(self, rfid_code, action_type, snapshot_path, operator="system", device_id=None):
        """记录出入库日志"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO access_logs (rfid_code, action_type, snapshot_path, operator, event_time, device_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (rfid_code, action_type, snapshot_path, operator, datetime.now(), device_id))
        conn.commit()
        conn.close()
        print(f"Logged {action_type} for {rfid_code}")

# 单例模式使用
db = DatabaseManager()
