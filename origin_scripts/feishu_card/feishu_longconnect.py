import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger
from lark_oapi.event.callback.model.p2_url_preview_get import P2URLPreviewGet, P2URLPreviewGetResponse
from typing import Any, Dict
import json
import datetime
import requests
import threading

# 配置信息
APP_ID = 'cli_a8d0e0c140169013'
APP_SECRET = 'yEc0E8Aoo8Mo9NPPzphidez51xB71HXW'

def log_info(title, content):
    """Simple formatted logger"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{timestamp}] \033[96m== {title} ==\033[0m")
    if isinstance(content, (dict, list)):
        print(json.dumps(content, indent=2, ensure_ascii=False))
    else:
        print(content)
    print("\033[90m" + "-"*50 + "\033[0m")

# --- Workflow API ---

def call_workflow_api(payload):
    api_url = "http://192.168.11.24:8088/open/workflow/execute"
    headers = {
        "X-API-Key": "wf_8bf2b0a20cf04804b098c99019854194",
        "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
        "Content-Type": "application/json",
        "Host": "192.168.11.24:8088",
        "Connection": "keep-alive"
    }
    
    try:
        log_info("Calling Workflow API (Async)", payload)
        resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
        log_info("Workflow API Response (Async)", {"status": resp.status_code, "text": resp.text})
    except Exception as e:
        log_info("Workflow API Error (Async)", str(e))

def prepare_common_payload(order_number, asset_list, remark):
    """准备通用的 payload 结构"""
    try:
        event_id_int = int(order_number)
    except (ValueError, TypeError):
        event_id_int = 0 
        
    return {
        "workflowId": 2028353753264754690,
        "inputs": {
            "event_id": event_id_int,
            "order_number_str": str(order_number),
            "asset_list": asset_list,
            "remark": remark,
            # 其他字段根据不同 handler 添加
        }
    }

# --- Handlers for different card types ---

def handle_asset_review(action, order_number):
    """处理资产复核卡片"""
    log_info("Handler", f"Processing Asset Review for {order_number}")
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    payload = prepare_common_payload(order_number, asset_list, remark)
    payload["inputs"]["card_type"] = "asset_review"
    
    call_workflow_api(payload)

def handle_asset_confirm(action, order_number):
    """处理资产确认卡片"""
    log_info("Handler", f"Processing Asset Confirm for {order_number}")
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    payload = prepare_common_payload(order_number, asset_list, remark)
    payload["inputs"]["card_type"] = "asset_confirm"
    
    call_workflow_api(payload)

def handle_asset_feedback(action, order_number):
    """处理资产反馈卡片"""
    log_info("Handler", f"Processing Asset Feedback for {order_number}")
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    payload = prepare_common_payload(order_number, asset_list, remark)
    payload["inputs"]["card_type"] = "asset_feedback"
    
    call_workflow_api(payload)

def handle_asset_visitor(action, order_number):
    """处理游客处理卡片"""
    log_info("Handler", f"Processing Asset Visitor for {order_number}")
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    event_user_ids = form_data.get("MultiSelect_3zegplt7pxi", [])
    
    payload = prepare_common_payload(order_number, asset_list, remark)
    payload["inputs"]["card_type"] = "asset_visitor"
    payload["inputs"]["event_user_ids"] = event_user_ids
    
    call_workflow_api(payload)

def handle_default(action, order_number):
    """默认处理逻辑"""
    log_info("Handler", f"Processing Default for {order_number}")
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    payload = prepare_common_payload(order_number, asset_list, remark)
    payload["inputs"]["card_type"] = "unknown"
    
    call_workflow_api(payload)

# 映射表
HANDLERS = {
    "asset_review": handle_asset_review,
    "asset_confirm": handle_asset_confirm,
    "asset_feedback": handle_asset_feedback,
    "asset_visitor": handle_asset_visitor
}

# --- Main Logic ---

def do_card_action_trigger(data: P2CardActionTrigger) -> Dict[str, Any]:
    """
    处理卡片回传交互 (card.action.trigger)
    """
    event = data.event
    action = event.action
    
    # 从 action.value 中提取关键信息
    action_value = action.value or {}
    order_number = action_value.get("order_number", "Unknown")
    card_type = action_value.get("card_type", "default")
    
    log_info("Card Action Triggered", {"card_type": card_type, "order_number": order_number, "action": action.name})

    toast_content = "操作成功"
    
    # 按钮点击处理
    if action.name == "confirm_button":
        handler = HANDLERS.get(card_type, handle_default)
        # 异步执行 Handler
        threading.Thread(target=handler, args=(action, order_number)).start()
        toast_content = "确认提交成功！（后台处理中）"

    elif action.name == "feedback_button":
        # 反馈按钮通常也可以调用同样的 API，或者有单独逻辑
        # 这里为了简单，假设反馈也走同样的 Handler，或者在这里区分
        # 如果需要区分反馈和确认，可以在 Handler 里判断 action.name
        # 或者使用单独的 Handler
        handler = HANDLERS.get(card_type, handle_default)
        threading.Thread(target=handler, args=(action, order_number)).start()
        toast_content = "反馈已收到，加急处理中。"
    else:
        toast_content = f"已收到表单提交！数据量: {len(action.form_value or {})}"

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
