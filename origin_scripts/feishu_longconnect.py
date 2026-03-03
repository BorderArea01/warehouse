import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger
from lark_oapi.event.callback.model.p2_url_preview_get import P2URLPreviewGet, P2URLPreviewGetResponse
from lark_oapi.api.im.v1.model import GetMessageRequest
from typing import Any, Dict, List, Optional
import json
import datetime
import re
import requests

# 配置信息
APP_ID = 'cli_a8d0e0c140169013'
APP_SECRET = 'yEc0E8Aoo8Mo9NPPzphidez51xB71HXW'

# Initialize API Client
api_client = lark.Client.builder() \
    .app_id(APP_ID) \
    .app_secret(APP_SECRET) \
    .log_level(lark.LogLevel.INFO) \
    .build()

def log_info(title, content):
    """Simple formatted logger"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{timestamp}] \033[96m== {title} ==\033[0m")
    if isinstance(content, (dict, list)):
        print(json.dumps(content, indent=2, ensure_ascii=False))
    else:
        print(content)
    print("\033[90m" + "-"*50 + "\033[0m")

def find_element_by_id(elements: Any, target_id: str) -> Optional[Dict]:
    """Recursively search for an element with a specific ID."""
    if isinstance(elements, dict):
        if elements.get("element_id") == target_id:
            return elements
        
        for key, value in elements.items():
            result = find_element_by_id(value, target_id)
            if result:
                return result
    
    elif isinstance(elements, list):
        for item in elements:
            result = find_element_by_id(item, target_id)
            if result:
                return result
    
    return None

def extract_markdown_contents(node: Any) -> List[str]:
    """Recursively extract all markdown contents."""
    texts = []
    if isinstance(node, dict):
        if node.get("tag") == "markdown":
            texts.append(node.get("content", ""))
        for key, value in node.items():
            texts.extend(extract_markdown_contents(value))
    elif isinstance(node, list):
        for item in node:
            texts.extend(extract_markdown_contents(item))
    return texts

import threading
import time

def process_workflow_async(action, order_number):
    """
    异步处理工作流请求，避免阻塞主线程导致飞书卡片超时
    """
    # 模拟网络延迟或耗时操作
    # time.sleep(1) 
    
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    api_url = "http://192.168.11.24:8088/open/workflow/execute"
    headers = {
        "X-API-Key": "wf_8bf2b0a20cf04804b098c99019854194",
        "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
        "Content-Type": "application/json",
        "Host": "192.168.11.24:8088",
        "Connection": "keep-alive"
    }
    
    try:
        # 尝试将 order_number 转为整数，如果失败则使用原始值或默认值
        try:
            event_id_int = int(order_number)
        except (ValueError, TypeError):
            log_info("Order Number Error", f"Cannot convert {order_number} to int")
            event_id_int = 0 # 或者抛出异常，视业务逻辑而定

        payload = {
            "workflowId": 2028353753264754690,
            "inputs": {
                "event_id": event_id_int,
                "asset_list": asset_list,
                "remark": remark
            }
        }
        
        log_info("Calling Workflow API (Async)", payload)
        resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
        log_info("Workflow API Response (Async)", {"status": resp.status_code, "text": resp.text})
        
    except Exception as e:
        log_info("Workflow API Error (Async)", str(e))

def do_card_action_trigger(data: P2CardActionTrigger) -> Dict[str, Any]:
    """
    处理卡片回传交互 (card.action.trigger)
    """
    # 解析关键信息
    event = data.event
    action = event.action
    operator = event.operator
    context = event.context
    
    # ... (原有提取逻辑保持不变)
    
    # 从 action.value 中直接获取 order_number
    action_value = action.value or {}
    order_number = action_value.get("order_number", "Unknown")
    
    # 尝试提取发生时间
    change_time = "Unknown"
    # (为了快速响应，这里可以考虑是否跳过 GetMessageRequest，或者也放到异步里去做？
    # 但如果后续逻辑不依赖它，可以暂时保留或简化)

    # ... (日志输出)
    
    # 根据按钮类型确定 Toast 内容
    if action.name == "confirm_button":
        # 启动异步线程处理工作流
        threading.Thread(target=process_workflow_async, args=(action, order_number)).start()
        toast_content = "确认提交成功！（后台处理中）"

    elif action.name == "feedback_button":
        toast_content = "反馈已收到，加急处理中。"
    else:
        toast_content = f"已收到表单提交！数据量: {len(action.form_value or {})}"

    # 构造响应 (立即返回)
    response = {
        "toast": {
            "type": "success",
            "content": toast_content
        },
        # 注意：如果不返回 card 字段，卡片内容不会刷新
        # 如果需要刷新卡片显示“已提交”，可以保留 card 字段
        # 这里为了演示快速返回，我们先只返回 toast，或者返回一个简单的静态卡片
        "card": {
            "type": "raw", 
            "data": {
                "schema": "2.0",
                "body": {
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": f"✅ {toast_content}"
                            }
                        }
                    ]
                }
            }
        }
    }
    
    log_info("Sending Response (Immediate)", {"Toast": toast_content})
    return response

def do_url_preview_get(data: P2URLPreviewGet) -> P2URLPreviewGetResponse:
    """
    处理链接预览 (url.preview.get)
    """
    log_info("URL Preview Request", lark.JSON.marshal(data))
    resp = {
        "inline": {
            "title": "链接预览测试",
        }
    }
    return P2URLPreviewGetResponse(resp)

# 注册事件处理器
event_handler = lark.EventDispatcherHandler.builder("", "") \
    .register_p2_card_action_trigger(do_card_action_trigger) \
    .register_p2_url_preview_get(do_url_preview_get) \
    .build()

def main():
    cli = lark.ws.Client(APP_ID, APP_SECRET,
                         event_handler=event_handler, 
                         log_level=lark.LogLevel.INFO)
    cli.start()

if __name__ == "__main__":
    main()
