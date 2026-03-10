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

# API 配置
FEEDBACK_API = {
    "url": "http://192.168.11.24:8088/open/workflow/execute",
    "key": "wf_9ec76b0a3a2a4be9ae386514c79e8390",
    "id": "2030844121164091393"
}

CONFIRM_API = {
    "url": "http://192.168.11.24:8088/open/workflow/execute",
    "key": "wf_91c35df1b27f4dd5acb732aee647d81b",
    "id": "2028353753264754690"
}

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

def call_workflow_api(payload, api_config=CONFIRM_API):
    api_url = api_config["url"]
    headers = {
        "X-API-Key": api_config["key"],
        "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
        "Content-Type": "application/json",
        "Host": "192.168.11.24:8088",
        "Connection": "keep-alive"
    }
    
    # 注入 workflowId
    payload["workflowId"] = api_config["id"]
    
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        log_info("Workflow API Error (Async)", str(e))

def prepare_common_payload(order_number, asset_list, remark, user_id=None):
    """准备通用的 payload 结构"""
    try:
        event_id_int = int(order_number)
    except (ValueError, TypeError):
        event_id_int = 0 
        
    inputs = {
        "event_id": event_id_int, # 注意：文档要求可能是 order_number 字符串，这里保持 int 尝试
        "asset_list": asset_list,
        "remark": remark,
    }
    
    if user_id:
        inputs["person_id"] = user_id
        
    return {
        # workflowId 由 call_workflow_api 注入
        "inputs": inputs
    }

def handle_asset_review(action, order_number, user_id):
    """处理资产复核卡片"""
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    payload = prepare_common_payload(order_number, asset_list, remark, user_id)
    
    log_info("Processing Asset Review", {
        "action": action.name,
        "order_number": order_number,
        "user_id": user_id,
        "form_data": form_data,
        "workflow_payload": payload
    })
    
    call_workflow_api(payload, CONFIRM_API)

def handle_asset_confirm(action, order_number, user_id):
    """处理资产确认卡片"""
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")

    payload = prepare_common_payload(order_number, asset_list, remark, user_id)

    log_info("Processing Asset Confirm", {
        "action": action.name,
        "order_number": order_number,
        "user_id": user_id,
        "form_data": form_data,
        "workflow_payload": payload
    })
    
    call_workflow_api(payload, CONFIRM_API)

def handle_asset_feedback(action, order_number, user_id):
    """处理资产反馈卡片 (确认按钮)"""
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    payload = prepare_common_payload(order_number, asset_list, remark, user_id)

    log_info("Processing Asset Feedback Confirm", {
        "action": action.name,
        "order_number": order_number,
        "user_id": user_id,
        "form_data": form_data,
        "workflow_payload": payload
    })
    
    call_workflow_api(payload, CONFIRM_API)

def handle_feedback_button_click(action, order_number, user_id):
    """处理卡片上的 '反馈问题' 按钮点击"""
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")
    
    # 获取卡片发送时的 change_time，如果没有则使用当前时间作为兜底
    action_value = action.value or {}
    change_time = action_value.get("change_time")
    if not change_time:
        change_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = prepare_common_payload(order_number, asset_list, remark, user_id)
    payload["inputs"]["change_time"] = change_time

    log_info("Processing Feedback Button Click", {
        "action": action.name,
        "order_number": order_number,
        "user_id": user_id,
        "change_time": change_time,
        "form_data": form_data,
        "workflow_payload": payload
    })
    
    call_workflow_api(payload, FEEDBACK_API)

def handle_asset_visitor(action, order_number, user_id):
    """处理游客处理卡片"""
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")

    payload = prepare_common_payload(order_number, asset_list, remark, user_id)
    
    log_info("Processing Asset Visitor", {
        "action": action.name,
        "order_number": order_number,
        "user_id": user_id,
        "form_data": form_data,
        "workflow_payload": payload
    })
    
    call_workflow_api(payload, CONFIRM_API)

def handle_default(action, order_number, user_id):
    """默认处理逻辑"""
    form_data = action.form_value or {}
    asset_list = form_data.get("input_assets", [])
    remark = form_data.get("input_remark", "")

    payload = prepare_common_payload(order_number, asset_list, remark, user_id)

    log_info("Processing Default (Unknown Type)", {
        "action": action.name,
        "order_number": order_number,
        "user_id": user_id,
        "form_data": form_data,
        "workflow_payload": payload,
    })
    
    call_workflow_api(payload, CONFIRM_API)

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

    action_value = action.value or {}
    order_number = action_value.get("order_number", "Unknown")
    card_type = action_value.get("card_type", "default")

    user_id = ""
    if event.operator:
        user_id = event.operator.user_id or event.operator.open_id or "unknown"
    
    toast_content = "操作成功"

    if action.name == "confirm_button":
        handler = HANDLERS.get(card_type, handle_default)
        threading.Thread(target=handler, args=(action, order_number, user_id)).start()
        toast_content = "确认提交成功！（后台处理中）"

    elif action.name == "feedback_button":
        handler = handle_feedback_button_click
        threading.Thread(target=handler, args=(action, order_number, user_id)).start()
        toast_content = "反馈已收到，加急处理中。"
    else:
        toast_content = f"已收到表单提交！数据量: {len(action.form_value or {})}"

    response = {
        "toast": {
            "type": "success",
            "content": toast_content
        },
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
