import lark_oapi as lark
from lark_oapi.api.im.v1 import *
import json
import os
from datetime import datetime
import random

# 配置信息
APP_ID = 'cli_a8d0e0c140169013'
APP_SECRET = 'yEc0E8Aoo8Mo9NPPzphidez51xB71HXW'
RECEIVE_ID = "ou_caa5a3e2bf2b2e99232737f1be08183b" 
RECEIVE_ID_TYPE = "open_id"

# 卡片 JSON 文件路径
CARD_JSON_PATH = r"/home/lzwc/project/warehouse/origin_scripts/feishu_card/资产变动单（待复核）.json"

def load_and_render_card():
    if not os.path.exists(CARD_JSON_PATH):
        print(f"File not found: {CARD_JSON_PATH}")
        return None

    with open(CARD_JSON_PATH, "r", encoding="utf-8") as f:
        card_content = f.read()

    # 准备数据
    order_number = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
    change_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 资产列表选项
    asset_options = [
        {"text": {"tag": "plain_text", "content": "显示器"}, "value": "monitor"},
        {"text": {"tag": "plain_text", "content": "键盘"}, "value": "keyboard"},
        {"text": {"tag": "plain_text", "content": "鼠标"}, "value": "mouse"}
    ]
    
    # 人员列表
    event_user_ids = [{"id": RECEIVE_ID}]

    # 1. 简单字符串替换
    card_content = card_content.replace("${order_number}", order_number)
    card_content = card_content.replace("${change_time}", change_time)
    card_content = card_content.replace("${remark}", "如果不属实，请点击此按钮反馈")

    try:
        card_json = json.loads(card_content)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        return None

    # 2. 复杂对象替换
    def process_nodes(node):
        if isinstance(node, dict):
            # 替换 options
            for key, value in node.items():
                if key == "options" and value == "${asset_list}":
                    node[key] = asset_options
                # 替换 persons 列表
                if key == "persons" and value == "${event_user_ids}":
                    node[key] = event_user_ids

            # 注入 order_number 和 card_type 到按钮回调 value
            if node.get("tag") == "button":
                behaviors = node.get("behaviors", [])
                for behavior in behaviors:
                    if behavior.get("type") == "callback" and "value" in behavior:
                        if isinstance(behavior["value"], dict):
                            behavior["value"]["order_number"] = order_number
                            behavior["value"]["card_type"] = "asset_review"

            # 递归处理子节点
            for key, value in node.items():
                process_nodes(value)
        
        elif isinstance(node, list):
            for item in node:
                process_nodes(item)

    process_nodes(card_json)
    return card_json

def main():
    card_json = load_and_render_card()
    if not card_json:
        return

    client = lark.Client.builder() \
        .app_id(APP_ID) \
        .app_secret(APP_SECRET) \
        .log_level(lark.LogLevel.DEBUG) \
        .build()

    request = CreateMessageRequest.builder() \
        .receive_id_type(RECEIVE_ID_TYPE) \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(RECEIVE_ID)
            .msg_type("interactive")
            .content(json.dumps(card_json))
            .build()) \
        .build()

    response = client.im.v1.message.create(request)

    if not response.success():
        print(f"发送失败: code: {response.code}, msg: {response.msg}, error: {response.error}")
        return

    print(f"发送成功! message_id: {response.data.message_id}")

if __name__ == "__main__":
    main()
