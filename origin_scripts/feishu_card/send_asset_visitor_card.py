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
CARD_JSON_PATH = r"/home/lzwc/project/warehouse/origin_scripts/feishu_card/资产变动单（游客处理）.json"

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
    
    # 相关人员选项
    user_options = [
        {"text": {"tag": "plain_text", "content": "管理员A"}, "value": RECEIVE_ID},
        {"text": {"tag": "plain_text", "content": "管理员B"}, "value": "ou_test_user_b"}
    ]

    # 1. 简单字符串替换
    card_content = card_content.replace("${order_number}", order_number)
    card_content = card_content.replace("${change_time}", change_time)
    
    # 使用占位符，后续在 process_nodes 中移除
    card_content = card_content.replace("${face_cap}", "img_v3_02uq_464e006d-8135-4a81-82a2-c37cdeb3d1cg")

    try:
        card_json = json.loads(card_content)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        return None

    # 2. 复杂对象替换 & 无效图片移除
    def process_nodes(node):
        if isinstance(node, dict):
            # 检查是否为无效图片
            if node.get("tag") == "img" and node.get("img_key") == "img_v2_placeholder":
                return True # 返回 True 表示此节点需要被删除

            # 替换 options
            for key, value in node.items():
                if key == "options" and value == "${asset_list}":
                    node[key] = asset_options
                if key == "options" and value == "${event_user_ids}":
                    node[key] = user_options

            # 注入 order_number 和 card_type 到按钮回调 value
            if node.get("tag") == "button":
                behaviors = node.get("behaviors", [])
                for behavior in behaviors:
                    if behavior.get("type") == "callback" and "value" in behavior:
                        if isinstance(behavior["value"], dict):
                            behavior["value"]["order_number"] = order_number
                            behavior["value"]["card_type"] = "asset_visitor"

            # 递归处理子节点
            keys_to_remove = []
            for key, value in node.items():
                if isinstance(value, list):
                    # 如果值是列表，遍历列表中的元素
                    new_list = []
                    for item in value:
                        # 如果 process_nodes 返回 False (不删除)，则保留
                        if not process_nodes(item):
                            new_list.append(item)
                    node[key] = new_list
                elif isinstance(value, dict):
                    # 如果值是字典，递归调用
                    if process_nodes(value):
                        keys_to_remove.append(key)
            
            for k in keys_to_remove:
                del node[k]
                
            return False # 返回 False 表示此节点不需要删除（除非它被上面的逻辑标记为删除了）
        
        elif isinstance(node, list):
            # 如果传入的是 list，通常由父级 dict 遍历处理
            # 但如果是根节点是 list，这里也处理一下
            new_list = []
            for item in node:
                if not process_nodes(item):
                    new_list.append(item)
            # 注意：这里无法直接修改 list 本身，只能修改内容
            node[:] = new_list
            return False

        return False

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
