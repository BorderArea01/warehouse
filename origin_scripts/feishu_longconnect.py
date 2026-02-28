import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger
from lark_oapi.event.callback.model.p2_url_preview_get import P2URLPreviewGet, P2URLPreviewGetResponse
from typing import Any, Dict

# 配置信息
APP_ID = 'cli_a8d0e0c140169013'
APP_SECRET = 'yEc0E8Aoo8Mo9NPPzphidez51xB71HXW'

def do_card_action_trigger(data: P2CardActionTrigger) -> Dict[str, Any]:
    """
    处理卡片回传交互 (card.action.trigger)
    """
    # 打印接收到的数据，便于调试
    print(f"[Card Action] Receive: {lark.JSON.marshal(data)}")
    
    action = data.event.action
    form_value = action.form_value or {}
    button_name = action.name
    
    print(f"[Card Action] Button: {button_name}, Form: {form_value}")

    # 根据按钮类型确定 Toast 内容
    if button_name == "confirm_button":
        toast_content = "确认提交成功！"
    elif button_name == "feedback_button":
        toast_content = "反馈已收到，加急处理中。"
    else:
        toast_content = f"已收到表单提交！数据量: {len(form_value)}"

    # 构造响应
    # 注意：为了解决 200830 错误 (JSON 2.0 无法更新为 1.0)，
    # 必须返回 raw 类型且 data 中包含 schema: 2.0
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
    
    print(f"[Card Action] Response: {response}")
    return response

def do_url_preview_get(data: P2URLPreviewGet) -> P2URLPreviewGetResponse:
    """
    处理链接预览 (url.preview.get)
    """
    print(f"[URL Preview] Receive: {lark.JSON.marshal(data)}")
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
