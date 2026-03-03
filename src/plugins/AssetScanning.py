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

# Local Imports
from src.config import Config
try:
    from src.plugins.ToAgent import ToAgent
except ImportError:
    ToAgent = None

# Configure logger for this module
logger = Config.get_logger("AssetScanning")

# ================= Configuration & Constants =================

# RFID Library Path
LIB_PATH = Config.RFID_LIB_PATH

# API Constants
MT_OK_ERR = 0
MAXANTCNT = 16
MAXEMBDATALEN = 128
MAXEPCBYTESCNT = 62
DEFAULT_DEPARTURE_TIMEOUT = 3.0  # Seconds to consider a tag gone

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
        logger.debug(f"Loading RFID dynamic library: {self.lib_path}")
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

    def __init__(self, conn_str: str = None, departure_timeout: float = DEFAULT_DEPARTURE_TIMEOUT):
        self.conn_str = conn_str or Config.RFID_CONN_STR
        self.departure_timeout = departure_timeout
        
        self.reader = RfidReader()
        self.inventory_state: Dict[str, float] = {}
        self.first_seen: Dict[str, float] = {}
        
        self.connected = False
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        self.log_dir = os.path.join(Config.PROJECT_ROOT, 'logs', 'asset')
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.to_agent = ToAgent(module_name="AssetScanning") if ToAgent else None

    def _format_time(self, dt_obj: datetime) -> str:
        """Format datetime as requested: YYYY-MM-DD HH:MM:SS"""
        return dt_obj.strftime("%Y-%m-%d %H:%M:%S")

    def start_monitoring(self):
        """Start the background monitoring thread."""
        ports = ['/dev/ttyACM0', '/dev/ttyACM1', '/dev/ttyACM2']
        connected = False

        for port in ports:
            logger.debug(f"Attempting to connect to RFID Reader at {port}...")
            if self.reader.connect(port):
                logger.info(f"RFID Reader Connected Successfully at {port}.")
                self.conn_str = port
                connected = True
                break
        
        if connected:
            self.connected = True
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
        else:
            logger.error(f"RFID Connection Failed! Tried ports: {', '.join(ports)}")
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
                    if not epc: # Skip empty EPCs
                        continue
                    if epc not in self.inventory_state:
                        self.first_seen[epc] = tag.get('timestamp', current_time)
                        self._log_asset_event(tag, "online")
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
            last_seen_float = self.inventory_state[epc]
            # Log offline event
            # Use last_seen_float as the event timestamp (when it actually disappeared)
            self._log_asset_event({'epc': epc, 'timestamp': last_seen_float}, "offline")
            
            del self.inventory_state[epc]
            if epc in self.first_seen:
                del self.first_seen[epc]

    def _log_asset_event(self, tag_data: Dict[str, Any], event_type: str):
        """Append event to daily JSONL log."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(self.log_dir, f"{today_str}_asset_log.jsonl")
        
        epc = tag_data.get('epc')
        
        # Deduplication logic is removed for online/offline events to capture all raw changes
        
        # Event time (when it happened)
        event_ts = tag_data.get('timestamp', time.time())
        event_dt = datetime.fromtimestamp(event_ts)
        
        # Log write time (now)
        now = datetime.now()

        record = {
            "timestamp": self._format_time(now),
            "event": event_type,
            "epc": epc,
            "event_time": self._format_time(event_dt),
            "rssi": tag_data.get('rssi'),
            "ant": tag_data.get('ant')
        }
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write log: {e}")

    def get_asset_changes(self, start_time_iso: str, end_time_iso: str) -> List[str]:
        """
        Analyze asset changes between start and end times (plus 8 seconds buffer) and return the list.
        This is a synchronous blocking call.
        """
        logger.info(f"Waiting 8 seconds for asset state to stabilize...")
        time.sleep(8)
        
        logger.info(f"Analyzing asset changes between {start_time_iso} and {end_time_iso} (+8s)...")
        
        try:
            # Handle both ISO and custom format for start_time
            if 'T' in start_time_iso:
                start_dt = datetime.fromisoformat(start_time_iso)
            else:
                start_dt = datetime.strptime(start_time_iso, "%Y-%m-%d %H:%M:%S")
                
            # Handle both ISO and custom format for end_time
            if 'T' in end_time_iso:
                end_dt = datetime.fromisoformat(end_time_iso)
            else:
                end_dt = datetime.strptime(end_time_iso, "%Y-%m-%d %H:%M:%S")
                
            analysis_end_dt = end_dt + timedelta(seconds=8)
            
            # Locate log file (assuming same day for simplicity)
            today_str = start_dt.strftime("%Y-%m-%d")
            log_file = os.path.join(self.log_dir, f"{today_str}_asset_log.jsonl")
            
            if not os.path.exists(log_file):
                logger.warning(f"No asset logs found for {today_str}.")
                return []
            
            epc_list: List[str] = []
            
            # Dictionary to count occurrences: {epc: [record1, record2, ...]}
            epc_occurrences: Dict[str, List[Dict]] = {}
            
            # Helper to reconstruct sessions from online/offline events
            # epc -> start_time_str
            pending_sessions: Dict[str, str] = {}
            
            # Scan log for events within the window
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        event = record.get('event')
                        epc = record.get('epc')
                        if not epc:
                            continue
                        
                        event_time_str = record.get('event_time', record.get('timestamp'))
                        
                        if event == 'online':
                            pending_sessions[epc] = event_time_str
                            
                        elif event == 'offline':
                            start_str = pending_sessions.get(epc)
                            if not start_str:
                                start_str = event_time_str 
                            
                            try:
                                end_dt_val = datetime.strptime(event_time_str, "%Y-%m-%d %H:%M:%S")
                                start_dt_val = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                                duration = int((end_dt_val - start_dt_val).total_seconds() * 1000)
                            except ValueError:
                                continue

                            # Make timezone aware if needed
                            if end_dt_val.tzinfo is None and start_dt.tzinfo is not None:
                                end_dt_val = end_dt_val.replace(tzinfo=start_dt.tzinfo)

                            # Check if this session ended during the visit window
                            # Also check if session started during window
                            is_within_window = False
                            
                            # Case 1: Session contained within window
                            if start_dt <= start_dt_val and end_dt_val <= analysis_end_dt:
                                is_within_window = True
                            # Case 2: Session started before window but ended within window
                            elif start_dt_val < start_dt and start_dt <= end_dt_val <= analysis_end_dt:
                                is_within_window = True
                            # Case 3: Session started within window but ends after (shouldn't happen with +8s wait, but possible)
                            elif start_dt <= start_dt_val <= analysis_end_dt:
                                is_within_window = True
                            # Case 4: Session covers the entire window (Started before, Ended after)
                            elif start_dt_val < start_dt and end_dt_val > analysis_end_dt:
                                is_within_window = True
                                
                            if is_within_window:
                                if epc not in epc_occurrences:
                                    epc_occurrences[epc] = []
                                
                                epc_occurrences[epc].append({
                                    'epc': epc,
                                    'start_ts': start_str,
                                    'end_ts': event_time_str,
                                    'duration_ms': duration
                                })
                                
                            # Clear pending
                            if epc in pending_sessions:
                                del pending_sessions[epc]
                                
                    except (ValueError, KeyError, json.JSONDecodeError):
                        continue
            
            # 4. Handle remaining pending sessions (Online without Offline)
            # If an asset appeared during the visit window and is still "Online", it counts as an arrival.
            for epc, start_str in pending_sessions.items():
                try:
                    # Parse start time
                    if 'T' in start_str:
                         start_dt_val = datetime.fromisoformat(start_str)
                    else:
                         start_dt_val = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                    
                    # Make timezone aware if needed
                    if start_dt_val.tzinfo is None and start_dt.tzinfo is not None:
                        start_dt_val = start_dt_val.replace(tzinfo=start_dt.tzinfo)
                    
                    # If it appeared AFTER the visit started (or during the window), count it.
                    # Note: If it appeared BEFORE the visit started, it was already there, so no change relative to "being there".
                    if start_dt_val >= start_dt and start_dt_val <= analysis_end_dt:
                        if epc not in epc_occurrences:
                             epc_occurrences[epc] = []
                         
                        epc_occurrences[epc].append({
                             'epc': epc,
                             'start_ts': start_str,
                             'end_ts': None, # Still online
                             'duration_ms': -1
                         })
                        logger.debug(f"EPC {epc} is still online (started {start_str}), counting as session.")
                except Exception as e:
                    logger.warning(f"Error processing pending session for {epc}: {e}")
                    continue

            # Deduplication logic: Use time-based merging (Debounce)
            # This handles signal jitter (split sessions) and detects ANY valid movement.
            
            for epc, records in epc_occurrences.items():
                if not records:
                    continue
                
                # Sort by start time
                records.sort(key=lambda x: x['start_ts'])
                
                merged_sessions = []
                if not records:
                    continue
                    
                # 1. Merge overlapping or close sessions (Gap < 2 seconds)
                current_session = records[0]
                
                for i in range(1, len(records)):
                    next_session = records[i]
                    
                    # Parse times for comparison
                    try:
                        # Helper to get datetime object from session dict
                        def get_dt(t_str):
                            if not t_str: return None
                            if 'T' in t_str: return datetime.fromisoformat(t_str)
                            return datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")

                        curr_end = get_dt(current_session['end_ts'])
                        next_start = get_dt(next_session['start_ts'])
                        
                        if curr_end and next_start:
                            # Calculate gap in seconds
                            gap = (next_start - curr_end).total_seconds()
                            
                            if gap < 2.0: # 2 seconds threshold
                                # Merge: extend end time and duration
                                current_session['end_ts'] = next_session['end_ts']
                                if current_session['duration_ms'] != -1 and next_session['duration_ms'] != -1:
                                    current_session['duration_ms'] += next_session['duration_ms'] + (gap * 1000)
                                elif next_session['duration_ms'] == -1:
                                    current_session['duration_ms'] = -1 # Becomes ongoing
                                continue
                    except Exception as e:
                        logger.warning(f"Error merging sessions for {epc}: {e}")
                    
                    # If not merged, push current and start new
                    merged_sessions.append(current_session)
                    current_session = next_session
                
                merged_sessions.append(current_session)
                
                # 2. Filter noise (Duration < 0.5s)
                # Exception: ongoing sessions (-1) are always valid
                valid_sessions = []
                for s in merged_sessions:
                    if s['duration_ms'] == -1 or s['duration_ms'] >= 500:
                        valid_sessions.append(s)
                
                if valid_sessions:
                    epc_list.append(epc)
                    logger.info(f"Detected change for {epc}: {len(valid_sessions)} valid session(s).")
                else:
                    logger.debug(f"Ignored noise for {epc} (all sessions too short).")

            return epc_list
            
        except Exception as e:
            logger.error(f"Analysis Error: {e}")
            return []

    def analyze_asset_changes(self, start_time_iso: str, end_time_iso: str):
        """
        Legacy method for backward compatibility or direct invocation.
        Now delegates to get_asset_changes but NO LONGER sends a report.
        It just logs the result for debugging purposes.
        """
        # Note: get_asset_changes already does the 5s sleep.
        epc_list = self.get_asset_changes(start_time_iso, end_time_iso)
        
        if epc_list:
            logger.info(f"Asset Analysis Result (Internal): Detected {len(epc_list)} changed assets: {epc_list}")
        else:
            logger.info("Asset Analysis Result (Internal): No changes detected.")

    def _send_asset_report(self, epc_list: List[str], changes: List[Dict[str, Any]], start_t: str, end_t: str):
        """Send formatted report to the Agent. (Deprecated/Unused)"""
        # This method is kept but not called by default flow anymore
        pass

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
