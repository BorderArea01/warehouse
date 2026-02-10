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
*   **实时上报**: 人员进入时立即通知服务器，并附带抓拍图片链接。

### 2. 资产流动追踪 (AssetScanning)
*   **RFID 盘点**: 通过串口连接 RFID 读写器，实时监控在库资产。
*   **状态追踪**: 自动记录资产上线（入库）和下线（出库/移除）事件。
*   **变动分析**: 在人员离场后，自动分析该时段内的资产变动情况（带走或放入的物品）。
*   **数据同步**: 生成资产变动报告并上报服务器。

### 3. 离场监控与事件闭环 (TimeCapture)
*   **全景监控**: 通过 RTSP 协议连接海康威视（Hikvision）摄像头。
*   **离场判定**: 后台线程实时分析视频流，当仓库内无人（超时）时判定为离场。
*   **自动闭环**: 计算停留时长，触发资产变动分析，并将完整记录（人员+时间+资产）上报系统。

## 系统架构与流程 (Architecture & Workflow)

### 1. 系统部署拓扑图
以下拓扑图展示了系统的物理部署架构、硬件连接方式以及网络通信链路。

```mermaid
graph TD
    classDef host fill:#E3F2FD,stroke:#1565C0,stroke-width:3px,color:#000000,font-size:16px;
    classDef device fill:#F5F5F5,stroke:#616161,stroke-width:2px,color:#000000,font-size:14px;
    classDef server fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px,color:#000000,font-size:14px;
    classDef db fill:#FFF3E0,stroke:#EF6C00,stroke-width:2px,color:#000000,font-size:14px;
    classDef note fill:#FFF9C4,stroke:#FBC02D,stroke-width:1px,color:#000000,font-size:13px;

    subgraph Warehouse [🏢 仓库现场 Warehouse Site]
        direction TB
        Host[🖥️ 树莓派 Pi 5<br/>Core Controller]:::host
        
        subgraph USB_Serial [本地直连 Local I/O]
            direction LR
            FaceCam[📷 USB 人脸抓拍相机<br/>Face Camera]:::device
            RFIDReader[📟 RFID 读写器<br/>RFID Reader]:::device
            RFIDAnt[📡 RFID 天线<br/>RFID Antenna]:::device
        end
        
        subgraph LAN_Dev [局域网设备 LAN Devices]
            HikCam[📹 海康威视全景相机<br/>Hikvision Camera]:::device
        end
        
        NoteHost[运行模块 Modules:<br/>1. FaceCapture 人脸<br/>2. AssetScanning 资产<br/>3. TimeCapture 离场<br/>4. MinioUploader 上传]:::note
        Host -.- NoteHost
    end

    subgraph Cloud [☁️ 服务器端 Backend Server]
        direction TB
        APIGateway[⚙️ 后端 API 服务<br/>Business Logic]:::server
        MinIO[🗄️ MinIO 对象存储<br/>Image Storage]:::server
        DB[(🛢️ 数据库<br/>MySQL/Redis)]:::db
        APIGateway <--> DB
    end

    FaceCam -- "USB / CSI" --> Host
    RFIDAnt -- "同轴电缆 Coaxial" --> RFIDReader
    RFIDReader -- "USB / 串口 ttyACM0" --> Host
    HikCam -- "RTSP 视频流 TCP" --> Host
    Host == "HTTP POST JSON<br/>人员/资产数据" ==> APIGateway
    Host == "HTTP POST File<br/>抓拍图片上传" ==> MinIO
    
    linkStyle 0,1,2 stroke:#616161,stroke-width:2px;
    linkStyle 3 stroke:#1565C0,stroke-width:2px,stroke-dasharray: 5 5;
    linkStyle 4,5 stroke:#2E7D32,stroke-width:3px;
```

### 2. 核心流程时序图
以下时序图展示了 **FaceCapture** (入口)、**AssetScanning** (资产) 和 **TimeCapture** (出口) 三大模块的协同工作流程。

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'fontSize': '18px', 'fontFamily': 'Microsoft YaHei, Arial', 'actorBkg': '#FFFFFF', 'actorBorder': '#000000', 'signalColor': '#000000', 'signalTextColor': '#000000', 'noteBkgColor': '#FFF9C4', 'noteBorderColor': '#FBC02D' }}}%%
sequenceDiagram
    autonumber
    
    box "硬件层 (Hardware)" #F5F5F5
        participant Cam as 摄像头/RTSP
        participant RFID as RFID读写器
    end

    box "核心插件层 (Plugins)" #E3F2FD
        participant Face as FaceCapture
        participant Time as TimeCapture
        participant Asset as AssetScanning
        participant Up as MinioUploader
        participant Agent as ToAgent
    end

    box "数据层 (Data)" #FFF3E0
        participant Local as 本地日志(JSONL)
    end

    box "服务端 (Server)" #E8F5E9
        participant Server as 后端服务器 API
    end

    Note over Face, Asset: 系统启动，各模块并行独立运行

    %% ============================================================
    %% 阶段一：人员进入流程 (Entry Process)
    %% ============================================================
    rect rgb(227, 242, 253)
        Note left of Face: 阶段一：人员进入
        Cam->>Face: 捕获实时画面
        Face->>Face: MediaPipe 检测到人员 (Debounce 0.6s)
        
        Face->>Server: [POST] /recognizeFace (人脸识别)
        Server-->>Face: 返回身份信息 (Name, UserID)

        Face->>Up: upload_file(抓拍图片)
        Up->>Server: [POST] /file/upload (MinIO)
        Server-->>Up: 返回 fileUrl
        Up-->>Face: 返回图片链接

        Face->>Local: 写入进入记录 (Start Time, UserID, Url)
        Face->>Agent: invoke("人员进入通知")
        Agent->>Server: [POST] /webhook/invoke
    end

    %% ============================================================
    %% 阶段二：资产监控 (Asset Monitoring - Continuous)
    %% ============================================================
    rect rgb(255, 248, 225)
        Note left of Asset: 阶段二：资产监控 (持续运行)
        loop 每100ms盘点
            RFID->>Asset: 读取标签列表 (Inventory)
            alt 发现新标签
                Asset->>Local: 记录 Event: online
            else 标签消失 > 3s
                Asset->>Local: 记录 Event: offline
            end
        end
    end

    %% ============================================================
    %% 阶段三：人员离开与闭环 (Exit & Analysis)
    %% ============================================================
    rect rgb(232, 245, 233)
        Note left of Time: 阶段三：人员离开与闭环
        Cam->>Time: RTSP 视频流分析
        Time->>Time: 检测仓库无人 (超时 5s)
        
        Time->>Local: 查找并关闭“进行中”的记录
        Local-->>Time: 返回完整记录 (含 Start/End Time)

        par 并行处理：资产分析
            Time->>Asset: analyze_asset_changes(Start, End)
            Asset->>Asset: sleep(5s) 等待状态稳定
            Asset->>Local: 读取该时段内的资产日志
            Asset->>Asset: 计算 移除(Out) 和 新增(In) 列表
            Asset->>Agent: invoke("资产变动报告")
            Agent->>Server: [POST] /webhook/invoke
        and 并行处理：流水上报
            Time->>Agent: invoke("完整进出流水记录")
            Note right of Time: 包含身份、起止时间、图片链接
            Agent->>Server: [POST] /webhook/invoke
        end
    end
```

## 环境要求 (Requirements)
*   Python 3.8+
*   依赖库：`mediapipe`, `opencv-python`, `requests`, `numpy` 等。
*   硬件：
    *   树莓派 Pi 5 或更高性能工控机（Ubuntu24.04）。
    *   USB/CSI 摄像头（用于人脸抓拍）。
    *   海康威视网络摄像头（用于全景监控）。
    *   串口 RFID 读写器（支持 moduleAPI）。

## 辅助工具 (Helper Scripts)
*   `scripts/test_rfid_web.py`: 启动一个 Web 服务器，用于局域网内手机远程测试 RFID 识别范围和蜂鸣器。
*   `scripts/fix_firewall.sh`: 自动配置 UFW 防火墙以允许 Web 服务端口 (8000)。
*   `scripts/verify_env.py`: 环境自检脚本，检查依赖库和 RFID 驱动是否正常。

## 快速开始 (Quick Start)

### 1. 安装依赖
```bash
# 1. 安装系统级依赖
sudo apt update && sudo apt install -y python3-pip python3-opencv

# 2. 安装 Python 依赖
pip install -r requirements.txt --break-system-packages
# 或
python3 -m pip install mediapipe requests opencv-python-headless --break-system-packages
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
│   │   ├── Uploader.py         # MinIO 文件上传模块
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
