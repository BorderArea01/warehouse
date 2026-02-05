# 资产扫描插件，使用RFID射频读取器获取脱离范围的资产RFID值import ctypes
import ctypes
import os
import sys
import time

# ================= 配置部分 =================
# 动态库路径：优先使用当前目录下的库文件
script_dir = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.join(script_dir, 'libModuleAPI.so')

if not os.path.exists(LIB_PATH):
    LIB_PATH = '/usr/local/lib/libModuleAPI.so'

# ================= 常量定义 =================
MT_OK_ERR = 0
MAXANTCNT = 16
MAXEMBDATALEN = 128
MAXEPCBYTESCNT = 62
MTR_PARAM_RF_ANTPOWER = 190

# ================= ctypes 结构体定义 =================
class TAGINFO(ctypes.Structure):
    _fields_ = [
        ("ReadCnt", ctypes.c_uint),
        ("RSSI", ctypes.c_int),
        ("AntennaID", ctypes.c_ubyte),
        ("Frequency", ctypes.c_uint),
        ("TimeStamp", ctypes.c_uint),
        ("EmbededDatalen", ctypes.c_ushort),
        ("EmbededData", ctypes.c_ubyte * MAXEMBDATALEN),
        ("Res", ctypes.c_ubyte * 2),
        ("Epclen", ctypes.c_ushort),
        ("PC", ctypes.c_ubyte * 2),
        ("CRC", ctypes.c_ubyte * 2),
        ("EpcId", ctypes.c_ubyte * MAXEPCBYTESCNT),
        ("Phase", ctypes.c_int),
        ("protocol", ctypes.c_int),
    ]

class AntPower(ctypes.Structure):
    _fields_ = [
        ("antid", ctypes.c_int),
        ("readPower", ctypes.c_ushort),
        ("writePower", ctypes.c_ushort),
    ]

class AntPowerConf(ctypes.Structure):
    _fields_ = [
        ("antcnt", ctypes.c_int),
        ("Powers", AntPower * MAXANTCNT),
    ]

# ================= RFID 读取器类 (复用) =================
class RfidReader:
    def __init__(self, lib_path=None):
        if lib_path is None:
            lib_path = LIB_PATH
        
        print(f"正在加载动态库: {lib_path}")
        # 显式加载 C++ 运行时库，防止 undefined symbol 错误
        try:
            ctypes.CDLL('libstdc++.so.6', mode=ctypes.RTLD_GLOBAL)
        except OSError:
            pass
            
        try:
            self.lib = ctypes.CDLL(lib_path)
        except OSError as e:
            print(f"加载库失败: {e}")
            print("请检查 libModuleAPI.so 是否存在且适用于当前系统架构(ARM/x86)")
            sys.exit(1)
        
        self.hreader = ctypes.c_int(0)
        
        # 定义函数原型
        self.lib.InitReader_Notype.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_char_p, ctypes.c_int]
        self.lib.InitReader_Notype.restype = ctypes.c_int
        
        self.lib.CloseReader.argtypes = [ctypes.c_int]
        
        self.lib.TagInventory_Raw.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_ushort, ctypes.POINTER(ctypes.c_int)]
        self.lib.TagInventory_Raw.restype = ctypes.c_int
        
        self.lib.GetNextTag.argtypes = [ctypes.c_int, ctypes.POINTER(TAGINFO)]
        self.lib.GetNextTag.restype = ctypes.c_int

        self.lib.ParamSet.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        self.lib.ParamSet.restype = ctypes.c_int

    def connect(self, conn_str, ant_cnt=1):
        b_conn_str = conn_str.encode('utf-8')
        ret = self.lib.InitReader_Notype(ctypes.byref(self.hreader), b_conn_str, ant_cnt)
        return ret == MT_OK_ERR

    # def set_power(self, ant_id, read_power, write_power): (Removed)

    def inventory(self, timeout_ms=200):
        ants = (ctypes.c_int * 1)(1)
        tag_cnt = ctypes.c_int(0)
        ret = self.lib.TagInventory_Raw(self.hreader, ants, 1, timeout_ms, ctypes.byref(tag_cnt))
        
        tags = []
        if ret == MT_OK_ERR and tag_cnt.value > 0:
            for _ in range(tag_cnt.value):
                tag_info = TAGINFO()
                self.lib.GetNextTag(self.hreader, ctypes.byref(tag_info))
                tags.append(self._parse_tag(tag_info))
        return tags

    def _parse_tag(self, tag_info):
        epc_bytes = tag_info.EpcId[:tag_info.Epclen]
        epc_hex = ''.join([f'{b:02X}' for b in epc_bytes])
        return {
            'epc': epc_hex,
            'rssi': tag_info.RSSI,
            'ant': tag_info.AntennaID,
            'read_count': tag_info.ReadCnt,
            'freq': tag_info.Frequency,
            'phase': tag_info.Phase
        }

    def close(self):
        if self.hreader:
            self.lib.CloseReader(self.hreader)
            self.hreader = None

# ================= 资产追踪逻辑 =================
class AssetTracker:
    def __init__(self, departure_timeout=3.0):
        """
        :param departure_timeout: 设备消失多少秒后被判定为"离场/移除"
        """
        self.inventory = {}  # 格式: {epc: last_seen_timestamp}
        self.departure_timeout = departure_timeout
        
    def update(self, detected_tags):
        """
        更新库存状态
        :param detected_tags: 本次盘点到的标签列表
        """
        current_time = time.time()
        detected_epcs = set()
        
        # 清除当前行 (为了防止状态行残留)
        clear_line = "\r" + " " * 50 + "\r"
        
        # 1. 处理检测到的设备
        for tag in detected_tags:
            epc = tag['epc']
            detected_epcs.add(epc)
            
            if epc not in self.inventory:
                # === 事件：发现新设备 ===
                sys.stdout.write(clear_line)
                print(f"\033[92m[+] 设备入库/上线: {epc} (RSSI: {tag['rssi']} dBm, Freq: {tag['freq']}, Phase: {tag['phase']})\033[0m")
            
            # 更新最后一次看到的时间
            self.inventory[epc] = current_time
            
        # 2. 检查消失的设备
        departed_epcs = []
        for epc, last_seen in self.inventory.items():
            # 如果超过 N 秒没看到，认为已移除
            if current_time - last_seen > self.departure_timeout:
                departed_epcs.append(epc)
                
        for epc in departed_epcs:
            # === 事件：设备移除 ===
            sys.stdout.write(clear_line)
            print(f"\033[91m[-] 设备出库/下线: {epc}\033[0m")
            del self.inventory[epc]
            
        return len(self.inventory)

# ================= 主程序 =================
if __name__ == "__main__":
    conn_str = "/dev/ttyACM0"
    if len(sys.argv) > 1:
        conn_str = sys.argv[1]

    reader = RfidReader()
    tracker = AssetTracker(departure_timeout=15.0) # 15秒无信号则视为移除
    
    print(f"正在连接读写器: {conn_str} ...")
    if reader.connect(conn_str):
        print("连接成功！")
        # reader.set_power(1, 2000, 2000) # 20dBm (Removed)
        
        print("\n=== 资产监控系统已启动 ===")
        print("说明: 绿色表示新增设备，红色表示移除设备")
        print("监控中 (按 Ctrl+C 停止)...")
        
        try:
            while True:
                # 快速盘点 (100ms)
                tags = reader.inventory(timeout_ms=100)
                
                # 更新追踪器状态
                current_count = tracker.update(tags)
                
                # 动态显示当前在库总数 (覆盖同一行，不换行)
                sys.stdout.write(f"\r当前在库设备数: {current_count}   ")
                sys.stdout.flush()
                
        except KeyboardInterrupt:
            print("\n\n监控停止")
        finally:
            reader.close()
            print("连接已关闭")
    else:
        print("连接失败！请检查设备连接。")
