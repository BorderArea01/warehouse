import cv2
import time
import os
import sys
import logging
from datetime import datetime, timedelta

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("VideoBackup")

class VideoBackup:
    """
    VideoBackup Plugin:
    - 运行在远端服务器（非树莓派）。
    - 根据给定的开始和结束时间，从海康威视摄像头获取录像回放并保存。
    """
    def __init__(self, output_dir="backups"):
        # RTSP 配置 (根据 doc/config.md)
        # 注意: 这里使用 tracks/101 进行回放，而不是 Channels/101 (直播)
        self.base_rtsp_url = "rtsp://admin:Lzwc%402025.@192.168.13.140:554/Streaming/tracks/101"
        self.output_dir = output_dir
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
    def _format_hikvision_time(self, dt: datetime) -> str:
        """
        将 datetime 对象转换为海康威视 RTSP 回放所需的时间格式。
        格式: YYYYMMDDTHHMMSS (例如: 20231027T083000)
        注意: 海康通常使用设备本地时间。
        """
        return dt.strftime("%Y%m%dT%H%M%S")

    def download_segment(self, start_time: datetime, end_time: datetime, filename: str = None) -> str:
        """
        下载指定时间段的录像。
        
        Args:
            start_time: 开始时间
            end_time: 结束时间
            filename: 输出文件名 (可选)
            
        Returns:
            str: 保存的文件路径，失败则返回 None
        """
        if filename is None:
            filename = f"backup_{start_time.strftime('%Y%m%d_%H%M%S')}.mp4"
            
        output_path = os.path.join(self.output_dir, filename)
        
        # 构造回放 URL
        # 参数: starttime 和 endtime
        start_str = self._format_hikvision_time(start_time)
        end_str = self._format_hikvision_time(end_time)
        
        playback_url = f"{self.base_rtsp_url}?starttime={start_str}&endtime={end_str}"
        logger.info(f"Connecting to RTSP Playback: {playback_url}")
        
        try:
            cap = cv2.VideoCapture(playback_url)
            if not cap.isOpened():
                logger.error("Failed to open RTSP stream. Check connection or time range.")
                return None
                
            # 获取视频属性
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            if fps == 0 or fps > 60:
                fps = 25.0 # 默认 FPS
                
            logger.info(f"Video Info: {width}x{height} @ {fps}fps")
            
            # 初始化视频写入器
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            
            frame_count = 0
            start_download = time.time()
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                out.write(frame)
                frame_count += 1
                
                if frame_count % 100 == 0:
                    sys.stdout.write(f"\rRecording frames: {frame_count}")
                    sys.stdout.flush()
            
            print() # Newline
            logger.info(f"Download complete. Saved to {output_path}")
            
            cap.release()
            out.release()
            return output_path
            
        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            if 'cap' in locals(): cap.release()
            if 'out' in locals(): out.release()
            return None

    def run_demo(self):
        """
        演示模式：下载过去 1 分钟的录像
        """
        logger.info("Running demo mode...")
        now = datetime.now()
        # 下载 5 分钟前的一段 30 秒视频作为测试
        start = now - timedelta(minutes=5)
        end = start + timedelta(seconds=30)
        
        logger.info(f"Attempting to download from {start} to {end}")
        self.download_segment(start, end)

if __name__ == "__main__":
    # 简单的命令行入口
    backup_service = VideoBackup()
    
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        backup_service.run_demo()
    else:
        print("Usage: python VideoBackup.py demo")
        print("Or import this class in your application.")
