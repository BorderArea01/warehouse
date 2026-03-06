import lark_oapi as lark
from lark_oapi.api.im.v1 import *
import json
import os
from datetime import datetime

# 配置信息
APP_ID = 'cli_a8d0e0c140169013'
APP_SECRET = 'yEc0E8Aoo8Mo9NPPzphidez51xB71HXW'
RECEIVE_ID = "ou_caa5a3e2bf2b2e99232737f1be08183b" 
RECEIVE_ID_TYPE = "open_id"

# 卡片 JSON 文件路径
CARD_JSON_PATH = r"/home/lzwc/project/warehouse/origin_scripts/feishu_card/人员进入提醒.json"

def load_and_render_card():
    if not os.path.exists(CARD_JSON_PATH):
        print(f"File not found: {CARD_JSON_PATH}")
        return None

    with open(CARD_JSON_PATH, "r", encoding="utf-8") as f:
        card_content = f.read()

    # 替换变量
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 简单的字符串替换
    card_content = card_content.replace("${current_time}", current_time)
    card_content = card_content.replace("${user_id}", RECEIVE_ID)
    card_content = card_content.replace("${face_cap}", "img_v3_02uq_464e006d-8135-4a81-82a2-c37cdeb3d1cg") 

    try:
        card_json = json.loads(card_content)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        return None

    # 移除无效的图片元素
    def remove_invalid_images(node):
        if isinstance(node, dict):
            # 如果是图片元素且 img_key 为 placeholder，则标记为删除
            if node.get("tag") == "img" and node.get("img_key") == "img_v2_placeholder":
                return True
            
            # 递归处理子节点
            keys_to_remove = []
            for key, value in node.items():
                if isinstance(value, list):
                    # 过滤列表中的元素
                    new_list = []
                    for item in value:
                        if not remove_invalid_images(item):
                            new_list.append(item)
                    node[key] = new_list
                elif isinstance(value, dict):
                    if remove_invalid_images(value):
                        keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del node[key]
                
        return False

    remove_invalid_images(card_json)

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
