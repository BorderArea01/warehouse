import requests
from requests import Session
from pathlib import Path
import json
import logging
from src.config import Config

logger = Config.get_logger("MinioUploader")

class MinioUploader:
    def __init__(
        self,
        upload_url: str = None,
        session: Session = None,
    ):
        # Use Config.MINIO_UPLOAD_URL as default if not provided
        self.upload_url = upload_url or Config.MINIO_UPLOAD_URL
        self.session = session or requests.Session()

    def upload_file(
        self,
        file_path: Path,
    ) -> dict:
        url = self.upload_url
        if not url:
            logger.error("Upload URL is not configured.")
            raise ValueError("Upload URL is not configured.")
            
        file_size = file_path.stat().st_size
        file_size_mb = file_size / 1024 / 1024
        
        # ANSI Colors
        COLOR_REQ = "\033[96m"
        COLOR_RES = "\033[94m"
        COLOR_RESET = "\033[0m"
        
        if file_size > 15 * 1024 * 1024:
            logger.error("【文件大小超限】")
            raise ValueError(f"文件大小 {file_size_mb:.2f} MB 超过限制 15 MB，上传失败")

        allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.bmp'}
        file_extension = file_path.suffix.lower()
        
        if file_extension not in allowed_extensions:
            logger.error("【文件类型不支持】")
            raise ValueError(f"文件类型 {file_extension} 不支持，只允许PDF和图片文件")

        # Log Request
        log_req = (
            f"\n{COLOR_REQ}{'='*30}\n"
            f"[发送] Module: MinioUploader\n"
            f"Uploading File: {file_path.name}\n"
            f"Size: {file_size_mb:.2f} MB\n"
            f"{'='*30}{COLOR_RESET}"
        )
        logger.info(log_req)

        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f)}
            try:
                resp = self.session.post(
                    url,
                    files=files,
                    timeout=300,
                )
                resp.raise_for_status()
                result = resp.json()
            except Exception as e:
                logger.error(f"Upload Request Failed: {e}")
                raise

        server_msg = result.get("msg", "")
        server_code = result.get("code")
        data = result.get("data") or {}

        # Log Response
        log_resp = (
            f"\n{COLOR_RES}{'='*30}\n"
            f"[返回] Module: MinioUploader\n"
            f"Status: {resp.status_code}\n"
            f"Response: {json.dumps(result, ensure_ascii=False, indent=2)}\n"
            f"{'='*30}{COLOR_RESET}"
        )
        logger.info(log_resp)

        if server_code != 200:
            logger.error("【错误】上传失败!")
            raise ValueError(f"服务器返回: code={server_code}, msg={server_msg}")

        if not data:
            logger.error("【错误】上传失败! 响应中缺少data字段")
            raise ValueError(f"服务器返回: code={server_code}, msg={server_msg}, 但缺少data字段")

        return data
