# Warehouse Monitoring System

## 简介 (Introduction)
本项目是一个基于计算机视觉的仓库进出监控系统。利用 YOLOv5 模型实时检测人员进出，通过人脸识别确认身份，并记录精确的进出时间。系统包含入口人脸抓拍（FaceCapture）和出口离场监控（TimeCapture）两个核心模块。

## 功能特性 (Features)
*   **实时人脸检测与抓拍 (FaceCapture)**
    *   调用本地摄像头（Index 0）进行实时监控。
    *   集成 YOLOv5n 模型检测人员，支持防误触（Debounce）与距离过滤。
    *   智能冷却机制：单次进入事件最多上报 3 次，随后进入 60 秒冷却期，避免重复记录。
    *   对接后端人脸识别接口，上传抓拍照片。
*   **离场监控 (TimeCapture)**
    *   通过 RTSP 协议连接海康威视（Hikvision）摄像头。
    *   后台线程实时分析视频流，监测人员离场状态（基于超时判定）。
    *   自动记录离开时间并同步至系统。
*   **数据记录与同步**
    *   本地 `visit_records.jsonl` JSONL 文件实时备份进出记录。
    *   通过 `ToAgent` 插件与后端 Agent 联动，将完整的人员流水信息写入数据库。

## 环境要求 (Requirements)
*   Python 3.8+
*   依赖库：`torch`, `opencv-python`, `ultralytics`, `requests` 等（详见 `requirements.txt`）。
*   硬件：支持 PyTorch/YOLOv5 推理的设备（如 PC 或高性能边缘计算设备）。

## 快速开始 (Quick Start)

### 1. 安装依赖
确保已安装 Python 环境，然后在项目根目录下运行：
```bash
pip install -r requirements.txt
```

### 2. 运行系统
```bash
python src/main.py
```
启动后：
*   **FaceCapture** 将在主线程运行，并弹出 OpenCV 窗口显示实时监控画面（按 `q` 或 `Ctrl+C` 退出）。
*   **TimeCapture** 将在后台线程运行，监控 RTSP 流。

## 目录结构 (Directory Structure)
```
warehouse/
├── src/
│   ├── main.py                 # 主程序入口
│   ├── plugins/                # 功能插件目录
│   │   ├── FaceCapture.py      # 入口人脸抓拍模块（含 YOLOv5 检测与 HTTP 上报）
│   │   ├── TimeCapture.py      # 出口监控模块（含 RTSP 流处理与离场判定）
│   │   ├── ToAgent.py          # 后端通信模块
│   │   └── AssetScanning.py    # 资产扫描模块（可选）
├── requirements.txt            # 项目依赖列表
├── visit_records.jsonl         # 本地访问记录（运行时自动生成）
└── yolov5n.pt                  # YOLOv5 预训练模型
```

## 配置说明 (Configuration)
目前主要配置项位于各插件类的 `__init__` 方法中，请根据实际部署环境进行修改：

*   **FaceCapture.py**:
    *   `self.face_api_url`: 后端人脸识别 API 地址。
    *   `self.confidence_threshold`: 人脸/人员检测置信度阈值。

*   **TimeCapture.py**:
    *   `self.rtsp_url`: 出口摄像头的 RTSP 视频流地址。
    *   `self.person_timeout`: 判定人员离场的超时时间（默认 5.0 秒）。
