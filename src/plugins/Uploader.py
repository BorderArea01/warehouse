import requests
from requests import Session
from pathlib import Path
import json
class MinioUploader:
    def __init__(
        self,
        upload_url: str = config.UPLOAD_API_ENDPOINT,
        session: Session = None,
    ):
        self.upload_url = upload_url
        self.session = session or requests.Session()

    def upload_file(
        self,
        file_path: Path,
    ) -> dict:
        url = self.upload_url
        file_size = file_path.stat().st_size
        file_size_mb = file_size / 1024 / 1024
        
        if file_size > 15 * 1024 * 1024:
            print("【文件大小超限】")
            raise ValueError(f"文件大小 {file_size_mb:.2f} MB 超过限制 15 MB，上传失败")

        allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.bmp'}
        file_extension = file_path.suffix.lower()
        
        if file_extension not in allowed_extensions:
            print("【文件类型不支持】")
            raise ValueError(f"文件类型 {file_extension} 不支持，只允许PDF和图片文件")

        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f)}
            resp = self.session.post(
                url,
                files=files,
                timeout=config.UPLOAD_TIMEOUT,
            )
            resp.raise_for_status()
            result = resp.json()


        print(f"  响应内容:")
        print(json.dumps(result, ensure_ascii=False, indent=4))
        server_msg = result.get("msg", "")
        server_code = result.get("code")
        data = result.get("data") or {}

        if server_code != 200:
            print("【错误】上传失败!")
            raise ValueError(f"服务器返回: code={server_code}, msg={server_msg}")

        if not data:
            print("【错误】上传失败! 响应中缺少data字段")
            raise ValueError(f"服务器返回: code={server_code}, msg={server_msg}, 但缺少data字段")

        print("【成功】上传完成!")
        print(f"  文件信息:")
        print(json.dumps(data, ensure_ascii=False, indent=4))

        return data
