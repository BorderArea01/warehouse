## 一、人脸捕获（src/plugins/FaceCapture.py）
在树莓派的串口外接相机上，捕获到人脸快照（以后可能会进行活体检测），并将快照通过接口上传到服务器进行人脸识别。
接收到返回信息之后，结合当前北京时间，形成人员进出流水记录，暂存为本地 JSON。
**注意：此时不发送给服务器，仅本地缓存。**

## 二、结束时间获取与上报（src/plugins/TimeCapture.py）
通过海康摄像头（仓库全景）监测人员是否离开。
1. 当检测到仓库内无人（连续5秒无活动）时，判定为一次“离开事件”。
2. 系统扫描本地 JSON 记录，查找所有状态为“进行中”的记录。
3. 将当前时间作为这些记录的“结束时间”，并计算停留时长。
4. **仅在此刻，将包含完整开始时间、结束时间的记录一次性发送给服务器 Agent，写入数据库。**
5. 如果系统重启或异常导致没有捕捉到结束时间，则该条记录作废，不予上报（因为没有完整的时间段信息）。

## 三、资产流水（src/plugins/AssetScanning.py）
树莓派会通过串口外接RFID读取模块，算法监测脱离范围的RFID标签，形成json，发给服务器，服务器结合最近的人员进出流水sql记录，发送确认单（通过飞书、企微等，具体开发此处不作讨论）给对应人员，对应人员勾选自己变动的资产并签名后，确认单返回给服务器，服务器形成资产进出流水，写入数据库。

## 四、远端录像备份
在树莓派之外的服务器，获取到人员进出流水的时间信息之后，去仓库摄像头截取对应时间段的录像备份。

## 服务统计
树莓派有三个服务：（异步/多线程）
1. 人脸捕获（树莓派+串口摄像头）（opencv捕获人脸图像发送服务器接口）
2. 资产流水（树莓派+串口RFID射频读取器）（获取到脱离范围的RFID标签，发送给服务器）
3. 获取结束时间（海康摄像头直播流）（opencv监测仓库的人是否走光）
远端服务器有一个服务：
1. 备份录像（海康摄像头直播流）

## 其他环境配置说明
硬件：树莓派pi5，海康摄像头（仓库摄像头），RFID射频（串口），摄像头模块（串口）
仓库摄像头视频流：rtsp://admin:Lzwc%402025.@192.168.13.140:554/Streaming/Channels/101
服务器人脸识别接口：http://scenemana.lzwcai.com/api/system/visitorRecord/recognizeFace
服务器Agent接口：（发送信息给Agent可以由Agent完成数据库写入）
    def __init__(
        self,
        employee_id: str = "2019323642451259394",
        user_id: str = "1868",
        base_url: str = "http://scenemana.lzwcai.com/api/system/employee/webhook/invoke",
    ) -> None:
        self.base_url = base_url
        self.employee_id = employee_id
        self.user_id = user_id
参考脚本：src\plugins\ToAgent.py
