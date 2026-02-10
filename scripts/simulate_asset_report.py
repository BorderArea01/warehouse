# -*- coding: utf-8 -*-
import sys
import os
import time
import logging
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.plugins.ToAgent import ToAgent

def simulate_report():
    # Configure logging to output to console
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'  # Simplified format since ToAgent adds its own headers
    )

    # Initialize ToAgent
    to_agent = ToAgent(module_name="AssetScanning")
    
    # Simulate times (UTC+8)
    bj_tz = timezone(timedelta(hours=8))
    now = datetime.now(bj_tz)
    start_dt = now - timedelta(seconds=15)
    end_dt = now - timedelta(seconds=5)
    
    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()
    
    # Simulate Assets
    # Case 1: Some assets removed and some added
    removed_assets = ["E20000190812023916908C82"]
    added_assets = ["E28068940000502C14A7322A", "E200001A5712011519602636"]
    
    # Construct Query (Consistent with AssetScanning.py)
    query = (
        f"资产变动报告：\n"
        f"时段：{start_str} 至 {end_str} (+5s)\n"
        f"移除资产 (Out): {', '.join(removed_assets) if removed_assets else '无'}\n"
        f"新增资产 (In): {', '.join(added_assets) if added_assets else '无'}"
    )
    
    print(f"--- Simulating Report ---")
    to_agent.invoke(query=query)

if __name__ == "__main__":
    simulate_report()
