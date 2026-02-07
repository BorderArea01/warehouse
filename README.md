# Warehouse Monitoring System

## 简介 (Introduction)
本项目是一个集成了计算机视觉和物联网技术的仓库智能监控系统。它利用 AI 模型进行人员进出管理，结合 RFID 技术进行资产流动追踪，实现对仓库环境的全方位自动化监控。

系统核心包含三大模块：
1.  **FaceCapture**: 基于 MediaPipe 的实时人脸检测与身份识别（入口）。
2.  **AssetScanning**: 基于 RFID 的资产实时盘点与变动追踪。
3.  **TimeCapture**: 基于 MediaPipe 与 RTSP 视频流的人员离场判定与事件闭环（出口）。

## 核心功能 (Features)

### 1. 实时人脸检测与抓拍 (FaceCapture)
*   **实时监控**: 调用本地摄像头（Index 0）进行不间断监控。
*   **智能识别**: 集成 Google MediaPipe (EfficientDet-Lite0) 模型检测人员，支持防误触（Debounce 0.6s）与距离过滤。
*   **身份验证**: 对接后端人脸识别接口，确认人员身份。
*   **流量控制**: 智能冷却机制，游客冷却 1s，普通人员冷却 5s；支持状态校验，避免重复记录未离场人员。
*   **实时上报**: 人员进入时立即通知服务器。

### 2. 资产流动追踪 (AssetScanning)
*   **RFID 盘点**: 通过串口连接 RFID 读写器，实时监控在库资产。
*   **状态追踪**: 自动记录资产上线（入库）和下线（出库/移除）事件。
*   **变动分析**: 在人员离场后，自动分析该时段内的资产变动情况（带走或放入的物品）。
*   **数据同步**: 生成资产变动报告并上报服务器。

### 3. 离场监控与事件闭环 (TimeCapture)
*   **全景监控**: 通过 RTSP 协议连接海康威视（Hikvision）摄像头。
*   **离场判定**: 后台线程实时分析视频流，当仓库内无人（超时）时判定为离场。
*   **自动闭环**: 计算停留时长，触发资产变动分析，并将完整记录（人员+时间+资产）上报系统。

## 环境要求 (Requirements)
*   Python 3.8+
*   依赖库：`mediapipe`, `opencv-python`, `requests`, `numpy` 等。
*   硬件：
    *   树莓派 Pi 5 或同等性能工控机。
    *   USB/CSI 摄像头（用于人脸抓拍）。
    *   海康威视网络摄像头（用于全景监控）。
    *   串口 RFID 读写器（支持 moduleAPI）。

## 快速开始 (Quick Start)

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 运行系统
```bash
# 必须在项目根目录下运行
python src/main.py
```

### 3. 运行模式
启动后，系统将自动加载以下服务：
*   **AssetScanning**: 后台线程，持续盘点 RFID 标签。
*   **TimeCapture**: 后台线程，监控 RTSP 视频流。
*   **FaceCapture**: 主线程（前台），显示实时监控窗口（按 `q` 或 `Ctrl+C` 退出）。

## 目录结构 (Directory Structure)
```
warehouse/
├── src/
│   ├── main.py                 # 主程序入口，负责服务编排
│   ├── plugins/                # 功能插件模块
│   │   ├── FaceCapture.py      # 入口人脸抓拍模块
│   │   ├── TimeCapture.py      # 出口离场监控模块
│   │   ├── AssetScanning.py    # RFID 资产追踪模块
│   │   ├── ToAgent.py          # 后端通信接口
│   │   ├── VideoBackup.py      # 录像回放下载工具
│   │   └── lib/                # 第三方动态库 (libModuleAPI.so)
│   └── utils/                  # 通用工具类
├── logs/                       # 日志目录
│   ├── system/                 # 系统运行日志 (main_run.log)
│   ├── person/                 # 人员进出记录 (JSONL)
│   └── asset/                  # 资产变动记录 (JSONL)
├── doc/                        # 项目文档
│   └── config.md               # 详细配置与逻辑说明
└── requirements.txt            # 项目依赖
```

## 配置说明 (Configuration)
主要配置项位于各插件源码顶部的常量定义中：

*   **FaceCapture.py**: API 地址、检测阈值、冷却时间。
*   **TimeCapture.py**: RTSP 地址、离场超时时间。
*   **AssetScanning.py**: 串口地址 (`/dev/ttyACM0`)、离场超时判定。
