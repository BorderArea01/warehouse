# -*- coding: utf-8 -*-
"""
Asset Scanning Plugin for Warehouse Monitoring System.

This module manages RFID tracking using a connected RFID reader.
It detects asset arrival (online) and removal (offline) events, logs them,
and analyzes changes during specific time windows (e.g., when a person visits).
"""

import ctypes
import os
import sys
import time
import json
import threading
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Set

# Configure logger for this module
logger = logging.getLogger("AssetScanning")

# Ensure project root is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

# Try importing ToAgent
try:
    from src.plugins.ToAgent import ToAgent
except ImportError:
    # Fallback for direct execution
    sys.path.append(os.path.join(project_root, 'src', 'plugins'))
    try:
        from ToAgent import ToAgent
    except ImportError:
        logger.warning("Could not import ToAgent. Server reporting will be disabled.")
        ToAgent = None

# ================= Configuration & Constants =================

# RFID Library Path
# 1. Check project root lib (Preferred)
LIB_PATH = os.path.join(project_root, 'lib', 'libModuleAPI.so')
if not os.path.exists(LIB_PATH):
    # 2. Check plugin local lib (Legacy)
    LIB_PATH = os.path.join(current_dir, 'lib', 'libModuleAPI.so')
    if not os.path.exists(LIB_PATH):
        # 3. System fallback
        LIB_PATH = '/usr/local/lib/libModuleAPI.so'

# API Constants
MT_OK_ERR = 0
MAXANTCNT = 16
MAXEMBDATALEN = 128
MAXEPCBYTESCNT = 62
DEFAULT_DEPARTURE_TIMEOUT = 3.0  # Seconds to consider a tag gone
DEFAULT_CONN_STR = "/dev/ttyACM0"

# ================= CTypes Structures =================

class TAGINFO(ctypes.Structure):
    """Structure representing RFID Tag Information."""
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

# ================= RFID Hardware Interface =================

class RfidReader:
    """Wrapper for the C++ RFID Module API."""

    def __init__(self, lib_path: str = None):
        self.lib_path = lib_path or LIB_PATH
        self.lib = None
        self.hreader = ctypes.c_int(0)
        self._load_library()
        self._setup_functions()

    def _load_library(self):
        logger.info(f"Loading RFID dynamic library: {self.lib_path}")
        # Explicitly load libstdc++ to prevent undefined symbol errors
        try:
            ctypes.CDLL('libstdc++.so.6', mode=ctypes.RTLD_GLOBAL)
        except OSError:
            pass

        try:
            self.lib = ctypes.CDLL(self.lib_path)
        except OSError as e:
            logger.error(f"Failed to load library: {e}")
            logger.error("Ensure libModuleAPI.so exists and matches system architecture.")
            raise RuntimeError(f"Failed to load RFID library: {e}")

    def _setup_functions(self):
        """Define argument and return types for C functions."""
        self.lib.InitReader_Notype.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_char_p, ctypes.c_int]
        self.lib.InitReader_Notype.restype = ctypes.c_int

        self.lib.CloseReader.argtypes = [ctypes.c_int]

        self.lib.TagInventory_Raw.argtypes = [
            ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_ushort, ctypes.POINTER(ctypes.c_int)
        ]
        self.lib.TagInventory_Raw.restype = ctypes.c_int

        self.lib.GetNextTag.argtypes = [ctypes.c_int, ctypes.POINTER(TAGINFO)]
        self.lib.GetNextTag.restype = ctypes.c_int

    def connect(self, conn_str: str, ant_cnt: int = 1) -> bool:
        """Connect to the RFID Reader."""
        b_conn_str = conn_str.encode('utf-8')
        ret = self.lib.InitReader_Notype(ctypes.byref(self.hreader), b_conn_str, ant_cnt)
        return ret == MT_OK_ERR

    def inventory(self, timeout_ms: int = 200) -> List[Dict[str, Any]]:
        """Perform a tag inventory scan."""
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

    def _parse_tag(self, tag_info: TAGINFO) -> Dict[str, Any]:
        """Convert TAGINFO structure to a Python dictionary."""
        epc_bytes = tag_info.EpcId[:tag_info.Epclen]
        epc_hex = ''.join([f'{b:02X}' for b in epc_bytes])
        return {
            'epc': epc_hex,
            'rssi': tag_info.RSSI,
            'ant': tag_info.AntennaID,
            'read_count': tag_info.ReadCnt,
            'freq': tag_info.Frequency,
            'phase': tag_info.Phase,
            'timestamp': time.time()
        }

    def close(self):
        """Close the connection to the reader."""
        if self.hreader:
            self.lib.CloseReader(self.hreader)
            self.hreader = None

# ================= Asset Scanning Service =================

class AssetScanning:
    """
    Asset Scanning Service.
    
    Monitors RFID tags and reports changes (Online/Offline).
    Integrates with TimeCapture to analyze assets moved during a person's visit.
    """

    def __init__(self, conn_str: str = DEFAULT_CONN_STR, departure_timeout: float = DEFAULT_DEPARTURE_TIMEOUT):
        self.conn_str = conn_str
        self.departure_timeout = departure_timeout
        
        self.reader = RfidReader()
        self.inventory_state: Dict[str, float] = {}  # {epc: last_seen_timestamp}
        
        self.connected = False
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        self.log_dir = os.path.join(project_root, 'logs', 'asset')
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.to_agent = ToAgent(module_name="AssetScanning") if ToAgent else None

    def start_monitoring(self):
        """Start the background monitoring thread."""
        logger.info(f"Connecting to RFID Reader at {self.conn_str}...")
        if self.reader.connect(self.conn_str):
            logger.info("RFID Reader Connected Successfully.")
            self.connected = True
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
        else:
            logger.error("RFID Connection Failed!")
            self.connected = False

    def stop_monitoring(self):
        """Stop the monitoring thread and close connection."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        if self.connected:
            self.reader.close()
            logger.info("RFID Reader Closed.")

    def _monitor_loop(self):
        """Main loop for detecting tags."""
        logger.info("Asset Monitoring Loop Started.")
        while self.running:
            try:
                # 1. Scan for tags (100ms timeout)
                tags = self.reader.inventory(timeout_ms=100)
                current_time = time.time()
                
                # 2. Process detected tags
                for tag in tags:
                    epc = tag['epc']
                    
                    if epc not in self.inventory_state:
                        # Event: New Device Online
                        self._log_asset_event(tag, "online")
                        logger.info(f"[+] Asset Online: {epc} (RSSI: {tag['rssi']})")
                    
                    self.inventory_state[epc] = current_time
                
                # 3. Process missing tags (Offline)
                self._check_departures(current_time)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(1)

    def _check_departures(self, current_time: float):
        """Identify tags that haven't been seen for a while."""
        departed_epcs = []
        for epc, last_seen in self.inventory_state.items():
            if current_time - last_seen > self.departure_timeout:
                departed_epcs.append(epc)
        
        for epc in departed_epcs:
            # Event: Device Offline
            self._log_asset_event({'epc': epc, 'timestamp': current_time}, "offline")
            logger.info(f"[-] Asset Offline: {epc}")
            del self.inventory_state[epc]

    def _log_asset_event(self, tag_data: Dict[str, Any], event_type: str):
        """Append event to daily JSONL log."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(self.log_dir, f"{today_str}_asset_log.jsonl")
        
        epc = tag_data.get('epc')
        
        # Deduplication Check
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    # Read lines from end (efficient for large logs? maybe just read all for now)
                    lines = f.readlines()
                    if lines:
                        # Check the last status of this EPC
                        for line in reversed(lines):
                            try:
                                last_rec = json.loads(line)
                                if last_rec.get('epc') == epc:
                                    if last_rec.get('event') == event_type:
                                        # Duplicate event (same state), ignore
                                        return
                                    else:
                                        # State changed, valid event
                                        break
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                logger.warning(f"Failed to check duplicates: {e}")

        record = {
            "timestamp": datetime.fromtimestamp(tag_data.get('timestamp', time.time())).isoformat(),
            "event": event_type,
            "epc": epc,
            "rssi": tag_data.get('rssi'),
            "freq": tag_data.get('freq'),
            "phase": tag_data.get('phase')
        }
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write log: {e}")

    def analyze_asset_changes(self, start_time_iso: str, end_time_iso: str):
        """
        Analyze asset changes between start and end times (plus 1 minute buffer).
        
        Args:
            start_time_iso: ISO formatted start time of the person's visit.
            end_time_iso: ISO formatted end time of the person's visit.
        """
        logger.info(f"Analyzing asset changes between {start_time_iso} and {end_time_iso} (+1m)...")
        
        try:
            start_dt = datetime.fromisoformat(start_time_iso)
            end_dt = datetime.fromisoformat(end_time_iso)
            analysis_end_dt = end_dt + timedelta(minutes=1)
            
            # Locate log file (assuming same day for simplicity)
            today_str = start_dt.strftime("%Y-%m-%d")
            log_file = os.path.join(self.log_dir, f"{today_str}_asset_log.jsonl")
            
            if not os.path.exists(log_file):
                logger.warning(f"No asset logs found for {today_str}.")
                return
            
            removed_assets: List[str] = []
            added_assets: List[str] = []
            
            # Scan log for events within the window
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        rec_time = datetime.fromisoformat(record['timestamp'])
                        
                        # Fix: Make rec_time timezone-aware if it's naive, to match start_dt
                        if rec_time.tzinfo is None and start_dt.tzinfo is not None:
                            # Assume record time is in same timezone as start_dt (e.g. UTC+8)
                            rec_time = rec_time.replace(tzinfo=start_dt.tzinfo)
                        
                        if start_dt <= rec_time <= analysis_end_dt:
                            if record['event'] == 'offline':
                                removed_assets.append(record['epc'])
                            elif record['event'] == 'online':
                                added_assets.append(record['epc'])
                    except (ValueError, KeyError):
                        continue
            
            if not removed_assets and not added_assets:
                logger.info(f"Analysis Completed: No asset changes detected between {start_time_iso} and {end_time_iso} (+1m).")
                # Optional: Send a 'No Change' report if you want confirmation? 
                # For now, just logging it is enough to prove it ran.
                return

            self._send_asset_report(removed_assets, added_assets, start_time_iso, end_time_iso)
            
        except Exception as e:
            logger.error(f"Analysis Error: {e}")

    def _send_asset_report(self, removed: List[str], added: List[str], start_t: str, end_t: str):
        """Send formatted report to the Agent."""
        if not self.to_agent:
            logger.warning("Agent not available. Cannot send report.")
            return

        query = (
            f"资产变动报告：\n"
            f"时段：{start_t} 至 {end_t} (+1min)\n"
            f"移除资产 (Out): {', '.join(removed) if removed else '无'}\n"
            f"新增资产 (In): {', '.join(added) if added else '无'}"
        )
        
        logger.info(f"Reporting to Agent: {query}")
        try:
            self.to_agent.invoke(query=query)
        except Exception as e:
            logger.error(f"Failed to send report to Agent: {e}")

if __name__ == "__main__":
    # Setup simple logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    scanner = AssetScanning()
    scanner.start_monitoring()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scanner.stop_monitoring()
