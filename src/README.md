# LangChain聊天机器人

这是一个使用LangChain和Flask实现的聊天机器人应用程序，是原Java版本（基于LangChain4j）的Python实现。

## 功能特点

- 使用LangChain与多种模型进行交互
- 支持Ollama本地模型
- 支持任何符合OpenAI规范的API（如OpenAI、Azure OpenAI、第三方兼容API等）
- 支持流式响应（Server-Sent Events）
- 消息持久化存储（SQLite数据库）
- RESTful API接口
- 支持自定义API URL和模型名称

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行应用

```bash
# 进入项目目录
cd src/python_langchain

# 运行应用
python app.py
```

应用将在http://localhost:5000上运行。

## API接口

### 获取所有消息

```
GET /messages
```

返回所有历史消息记录。

### 流式聊天

```
GET /stream?prompt=你的问题
```

以流式方式返回AI的回答，使用Server-Sent Events格式。

### 普通聊天

```
POST /chat
Content-Type: application/json

{
  "prompt": "你的问题"
}
```

返回AI的完整回答。

### 获取配置

```
GET /config
```

返回当前的API配置，包括模型名称、API类型、API URL等。

### 更新配置

```
POST /config
Content-Type: application/json

{
  "model_name": "llama3",
  "api_base_url": "http://localhost:11434",
  "api_type": "ollama",
  "api_key": "your-api-key"  // 仅OpenAI兼容API需要
}
```

更新API配置。可以只更新其中一个或多个参数。

## 项目结构

- `app.py`: 主应用程序入口
- `models.py`: 数据模型定义
- `db_service.py`: 数据库服务
- `chat_service.py`: 聊天服务
- `__init__.py`: 包初始化文件
- `static/`: 静态文件目录，包含前端页面

## 配置API

### Ollama配置（默认）

- API类型: ollama
- 模型名称: llama3
- API URL: http://localhost:11434
- API密钥: 不需要

### OpenAI兼容API配置示例

- API类型: openai
- 模型名称: gpt-3.5-turbo
- API URL: https://api.openai.com/v1
- API密钥: 您的OpenAI API密钥

### 第三方兼容API配置示例

- API类型: openai
- 模型名称: 根据第三方API要求
- API URL: 第三方API的URL
- API密钥: 第三方API提供的密钥

可以通过以下方式修改配置：

1. 在代码中直接修改`app.py`：

```python
chat_service = ChatService(
    model_name="模型名称",
    api_base_url="API基础URL",
    api_type="ollama或openai",
    api_key="API密钥(仅OpenAI兼容API需要)"
)
```

2. 通过API接口动态修改（见上文API接口说明）

3. 通过Web界面修改（点击"显示/隐藏配置"按钮） 