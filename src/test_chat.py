import os
import sys

# 添加当前目录到路径，以便导入模块
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from chat_service import ChatService

def test_chat():
    """测试聊天功能"""
    # 初始化聊天服务
    chat_service = ChatService(model_name="llama3")
    
    # 测试普通聊天
    prompt = "你好，请介绍一下自己"
    print(f"用户: {prompt}")
    
    # 定义回调函数，用于打印流式响应
    def print_token(token):
        print(token, end="", flush=True)
    
    # 调用聊天方法
    response = chat_service.chat(prompt, callback=print_token)
    print("\n\n完整响应:", response)
    
    # 获取所有消息
    messages = chat_service.get_messages()
    print(f"\n消息历史记录 (共{len(messages)}条):")
    for msg in messages:
        print(f"[{msg.sender}] {msg.created_at}: {msg.content[:50]}...")

if __name__ == "__main__":
    test_chat() 