import lark_oapi as lark
from lark_oapi.api.im.v1 import *
import json
import os
from datetime import datetime

# 配置你的 App ID 和 App Secret
APP_ID = 'cli_a8d0e0c140169013'
APP_SECRET = 'yEc0E8Aoo8Mo9NPPzphidez51xB71HXW'

# 你的 Open ID (请确保这个 ID 是正确的)
# RECEIVE_ID = "ou_5c041720bc5a15235d6026ef118d77c9" 
RECEIVE_ID = "ou_caa5a3e2bf2b2e99232737f1be08183b" 
RECEIVE_ID_TYPE = "open_id"

# 卡片 JSON 文件路径
CARD_JSON_PATH = r"/home/lzwc/project/warehouse/origin_scripts/卡片源代码（供参考，禁止直接改动）.json"

def load_and_render_card():
    # 1. 读取 JSON 文件
    with open(CARD_JSON_PATH, "r", encoding="utf-8") as f:
        card_content = f.read()

    # 2. 准备替换的数据
    # 注意：简单的字符串替换无法处理 "${asset_list}" 这种需要替换为 JSON 数组的情况
    # 所以我们需要先解析 JSON，再遍历替换，或者用更巧妙的方法
    
    # 构造选项列表
    asset_options = [
        {"text": {"tag": "plain_text", "content": "显示器"}, "value": "monitor"},
        {"text": {"tag": "plain_text", "content": "键盘"}, "value": "keyboard"},
        {"text": {"tag": "plain_text", "content": "鼠标"}, "value": "mouse"}
    ]
    
    # 这里我们采用一种混合策略：先替换简单的字符串变量，再解析 JSON 替换复杂对象
    
    # 替换简单变量
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    card_content = card_content.replace("${order_number}", "ORD-TEST-001")
    card_content = card_content.replace("${user_id}", RECEIVE_ID)
    card_content = card_content.replace("${change_time}", current_time)
    card_content = card_content.replace("${remark}", "如果不属实，请点击此按钮反馈")
    
    # 解析为 Python 对象
    card_json = json.loads(card_content)
    
    # 3. 替换复杂对象 (options)
    # 我们需要找到那个 multi_select_static 组件并替换它的 options
    # 同时，我们需要将 order_number 注入到按钮的 value 中，以便回调时能获取到
    order_number_val = "ORD-TEST-001"
    
    try:
        # 递归查找并替换 options="${asset_list}" 以及注入 order_number
        def process_nodes(node):
            if isinstance(node, dict):
                # Check for options replacement
                for key, value in node.items():
                    if key == "options" and value == "${asset_list}":
                        node[key] = asset_options
                
                # Check for button behaviors
                if node.get("tag") == "button":
                    behaviors = node.get("behaviors", [])
                    for behavior in behaviors:
                        if behavior.get("type") == "callback" and "value" in behavior:
                            # Inject order_number into the callback value
                            if isinstance(behavior["value"], dict):
                                behavior["value"]["order_number"] = order_number_val

                # Recursively process children
                for key, value in node.items():
                    process_nodes(value)
            
            elif isinstance(node, list):
                for item in node:
                    process_nodes(item)
                    
        process_nodes(card_json)
        
    except Exception as e:
        print(f"替换变量失败: {e}")
        return None

    return card_json

def main():
    # 加载并渲染卡片
    card_json = load_and_render_card()
    if not card_json:
        return

    # 创建 Client
    client = lark.Client.builder() \
        .app_id(APP_ID) \
        .app_secret(APP_SECRET) \
        .log_level(lark.LogLevel.DEBUG) \
        .build()

    # 构造请求
    request = CreateMessageRequest.builder() \
        .receive_id_type(RECEIVE_ID_TYPE) \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(RECEIVE_ID)
            .msg_type("interactive")
            .content(json.dumps(card_json)) # 这里再次序列化为字符串
            .build()) \
        .build()

    # 发送请求
    response = client.im.v1.message.create(request)

    # 处理响应
    if not response.success():
        print(f"发送失败: code: {response.code}, msg: {response.msg}, error: {response.error}")
        return

    print(f"发送成功! message_id: {response.data.message_id}")

if __name__ == "__main__":
    main()
