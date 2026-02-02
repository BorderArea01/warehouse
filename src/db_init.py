import sqlite3
import os

# 数据库文件路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'warehouse.db')

def init_db():
    print(f"Initializing database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 创建资产表 (Assets)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rfid_code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        model TEXT,
        spec TEXT,
        category TEXT,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    print("Table 'assets' check/create done.")

    # 2. 创建出入库记录表 (AccessLogs)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS access_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rfid_code TEXT NOT NULL,
        action_type TEXT NOT NULL,  -- 'IN' or 'OUT'
        snapshot_path TEXT,
        operator TEXT,
        event_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        device_id TEXT,
        FOREIGN KEY (rfid_code) REFERENCES assets (rfid_code)
    )
    ''')
    print("Table 'access_logs' check/create done.")

    # 3. 创建索引 (可选，优化查询)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_logs_rfid ON access_logs(rfid_code)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_logs_time ON access_logs(event_time)')
    print("Indices check/create done.")

    conn.commit()
    conn.close()
    print("Database initialization completed successfully.")

if __name__ == "__main__":
    # 确保父目录存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
