import os
import sys
import time
import json
import traceback
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory
from flask_cors import CORS
import sqlite3
from werkzeug.utils import secure_filename
from langchain_community.chat_models import ChatOllama, ChatOpenAI
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import AIMessage, HumanMessage
from chat_service import ChatService
from queue import Queue

app = Flask(__name__)
CORS(app)

# 静态文件目录
app.static_folder = ''

# API URL前缀
API_PREFIX = '/api'

# SQLite数据库文件路径
DB_PATH = 'messages.db'

# 文件上传配置
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制上传文件最大为16MB

# 创建基础数据库和会话表
def initialize_database():
    try:
        # 连接到SQLite数据库
        connection = sqlite3.connect(DB_PATH)
        cursor = connection.cursor()
        
        # 创建会话信息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_name TEXT NOT NULL,
                table_name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 检查是否有现有会话，如果没有创建一个默认会话
        cursor.execute("SELECT COUNT(*) as count FROM sessions")
        result = cursor.fetchone()
        if result and result[0] == 0:
            create_new_session_table('默认会话', connection)
        
        connection.commit()
        print("数据库初始化成功")
    except Exception as e:
        print(f"数据库初始化失败: {e}")
        # 不再切换到内存模式，直接抛出异常
        raise e
    finally:
        if connection:
            connection.close()

# 创建新的会话表
def create_new_session_table(session_name, connection=None):
    close_conn = False
    try:
        if connection is None:
            connection = sqlite3.connect(DB_PATH)
            close_conn = True
        
        cursor = connection.cursor()
        
        # 获取下一个表名
        cursor.execute("SELECT COALESCE(MAX(CAST(SUBSTR(table_name, 5) AS INTEGER)), 0) + 1 as next_id FROM sessions")
        result = cursor.fetchone()
        next_id = result[0] if result else 1
        table_name = f"chat{next_id}"
        
        # 创建新的聊天表
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 添加会话记录
        cursor.execute(
            "INSERT INTO sessions (session_name, table_name) VALUES (?, ?)",
            (session_name, table_name)
        )
        
        if close_conn:
            connection.commit()
        
        # 获取最后插入的ID
        cursor.execute("SELECT last_insert_rowid()")
        session_id = cursor.fetchone()[0]
        
        print(f"创建新会话表 {table_name} 成功")
        return {'id': session_id, 'session_name': session_name, 'table_name': table_name}
    except Exception as e:
        print(f"创建新会话表失败: {e}")
        if close_conn:
            connection.rollback()
        return None
    finally:
        if close_conn and connection:
            connection.close()

# 调用数据库初始化
initialize_database()

# 获取数据库连接
def get_db_connection():
    try:
        return sqlite3.connect(DB_PATH)
    except Exception as e:
        print(f"数据库连接失败: {e}")
        raise e  # 抛出异常而不是返回None

# 流式回调处理器
class StreamingCallbackHandler(BaseCallbackHandler):
    def __init__(self, queue):
        self.queue = queue

    def on_llm_new_token(self, token, **kwargs):
        self.queue.put(token)

# API配置数据
config = {
    'api_type': 'ollama',  # ollama or openai
    'model_name': 'deepseek-r1:8b',  # 默认模型
    'api_base_url': 'http://localhost:11434',  # 默认API URL
    'api_key': None,  # 可选
    'use_rag': False,  # 默认不使用RAG
    'embedding_model': 'deepseek-r1:8b'  # 默认嵌入模型
}

# 创建聊天服务实例
chat_service = ChatService(
    model_name=config['model_name'],
    api_base_url=config['api_base_url'],
    api_type=config['api_type'],
    api_key=config['api_key'],
    embedding_model=config['embedding_model']
)

# 检查文件扩展名是否允许
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    """返回主页"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route(f'{API_PREFIX}/config', methods=['GET', 'POST'])
@app.route('/config', methods=['GET', 'POST'])  # 同时保留旧路径以兼容
def handle_config():
    global config
    if request.method == 'POST':
        data = request.get_json()
        # 更新配置
        for key in data:
            if key in config:
                config[key] = data[key]
        
        # 更新聊天服务
        chat_service.update_model(
            model_name=config['model_name'],
            api_base_url=config['api_base_url'],
            api_type=config['api_type'],
            api_key=config['api_key'],
            embedding_model=config['embedding_model']
        )
        
        return jsonify(config)
    else:
        return jsonify(config)

# 文件上传API
@app.route(f'{API_PREFIX}/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '没有文件部分'}), 400
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
        
    if file and allowed_file(file.filename):
        # 安全地保存文件名
        timestamp = int(time.time())
        filename = secure_filename(f"{timestamp}_{file.filename}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            # 获取分块参数（如果有）
            chunk_size = request.form.get('chunk_size', None)
            chunk_overlap = request.form.get('chunk_overlap', None)
            
            # 转换为整数（如果提供）
            if chunk_size:
                try:
                    chunk_size = int(chunk_size)
                except ValueError:
                    chunk_size = None
            
            if chunk_overlap:
                try:
                    chunk_overlap = int(chunk_overlap)
                except ValueError:
                    chunk_overlap = None
            
            # 保存文件
            file.save(file_path)
            
            # 处理PDF文件，传入自定义分块参数
            result = chat_service.document_service.process_pdf(
                file_path, 
                file.filename,
                custom_chunk_size=chunk_size,
                custom_chunk_overlap=chunk_overlap
            )
            
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': f'处理文件失败: {str(e)}'}), 500
    else:
        return jsonify({'error': '不支持的文件类型，仅支持PDF'}), 400

# 获取上传的文件列表
@app.route(f'{API_PREFIX}/files', methods=['GET'])
def get_files():
    files = chat_service.document_service.get_uploaded_files()
    return jsonify({
        'count': len(files),
        'files': files
    })

# 删除文件
@app.route(f'{API_PREFIX}/files/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    result = chat_service.document_service.delete_file(file_id)
    
    if result['status'] == 'success':
        return jsonify(result)
    else:
        return jsonify(result), 404

# 获取所有会话
@app.route(f'{API_PREFIX}/sessions', methods=['GET'])
def get_sessions():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, session_name, table_name, created_at FROM sessions ORDER BY id DESC")
        session_rows = cursor.fetchall()
        
        # 将元组转换为字典列表
        sessions = []
        for row in session_rows:
            sessions.append({
                "id": row[0],
                "session_name": row[1],
                "table_name": row[2],
                "created_at": row[3]
            })
            
        return jsonify(sessions)
    except Exception as e:
        print(f"获取会话失败: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

# 创建新会话
@app.route(f'{API_PREFIX}/sessions', methods=['POST'])
def create_session():
    data = request.get_json()
    session_name = data.get('session_name', '新会话')
    
    try:
        conn = get_db_connection()
        session = create_new_session_table(session_name, conn)
        if not session:
            return jsonify({"error": "创建会话失败"}), 500
        
        conn.commit()
        return jsonify(session)
    except Exception as e:
        print(f"创建会话失败: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

# 删除会话
@app.route(f'{API_PREFIX}/sessions/<int:session_id>', methods=['DELETE'])
def delete_session(session_id):
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "数据库连接失败"}), 500
            
        cursor = conn.cursor()
        cursor.execute("SELECT table_name FROM sessions WHERE id = ?", (session_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "会话不存在"}), 404
        
        table_name = result[0]
        if not table_name:
            return jsonify({"error": "会话表名不存在"}), 500
        
        # 删除聊天表
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        
        # 删除会话记录
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        
        # 如果删除后没有会话了，创建一个默认会话
        cursor.execute("SELECT COUNT(*) as count FROM sessions")
        count_result = cursor.fetchone()
        if count_result and count_result[0] == 0:
            create_new_session_table('默认会话', conn)
        
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"删除会话失败: {e}")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

# 重命名会话
@app.route(f'{API_PREFIX}/sessions/<int:session_id>', methods=['PUT'])
def rename_session(session_id):
    data = request.get_json()
    new_name = data.get('session_name')
    
    if not new_name:
        return jsonify({"error": "缺少新的会话名称"}), 400
    
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "数据库连接失败"}), 500
            
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET session_name = ? WHERE id = ?", (new_name, session_id))
        if cursor.rowcount == 0:
            return jsonify({"error": "会话不存在"}), 404
        
        cursor.execute("SELECT id, session_name, table_name, created_at FROM sessions WHERE id = ?", (session_id,))
        session = cursor.fetchone()
        
        conn.commit()
        return jsonify(session)
    except Exception as e:
        print(f"重命名会话失败: {e}")
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route(f'{API_PREFIX}/messages')
@app.route('/messages')  # 同时保留旧路径以兼容
def get_messages():
    table_name = request.args.get('table_name')
    if not table_name:
        return jsonify([])
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT id, sender, content, timestamp FROM {table_name} ORDER BY id")
        messages = cursor.fetchall()
        
        # 确保返回格式正确 - 将元组转换为字典列表
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "id": msg[0],
                "sender": msg[1],
                "content": msg[2],
                "timestamp": msg[3]
            })
        
        return jsonify(formatted_messages)
    except Exception as e:
        print(f"获取消息失败: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route(f'{API_PREFIX}/save_message', methods=['POST'])
@app.route('/save_message', methods=['POST'])  # 同时保留旧路径以兼容
def save_message():
    data = request.get_json()
    table_name = data.get('table_name')
    sender = data.get('sender')
    content = data.get('content')
    timestamp = data.get('timestamp')
    
    if not all([table_name, sender, content]):
        return jsonify({"error": "缺少必要参数"}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO {table_name} (sender, content, timestamp) VALUES (?, ?, ?)",
            (sender, content, timestamp)
        )
        message_id = cursor.lastrowid
        conn.commit()
        return jsonify({"status": "success", "message_id": message_id})
    except Exception as e:
        print(f"保存消息失败: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route(f'{API_PREFIX}/delete_message', methods=['DELETE'])
@app.route('/delete_message/<int:message_id>', methods=['DELETE'])  # 同时保留旧路径以兼容
def delete_message():
    data = request.get_json()
    table_name = data.get('table_name')
    message_id = data.get('message_id')
    
    if not all([table_name, message_id]):
        return jsonify({"error": "缺少必要参数"}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (message_id,))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"删除消息失败: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route(f'{API_PREFIX}/stream')
@app.route('/stream')  # 同时保留旧路径以兼容
def stream():
    prompt = request.args.get('prompt', '')
    table_name = request.args.get('table_name', '')
    use_rag = request.args.get('use_rag', 'false').lower() == 'true'
    file_ids_str = request.args.get('file_ids', '[]')
    
    try:
        file_ids = json.loads(file_ids_str)
    except json.JSONDecodeError:
        file_ids = []
    
    if not prompt:
        return jsonify({"error": "Missing required parameters"}), 400
    
    try:
        def generate():
            # 使用聊天服务的流式处理功能
            for token in chat_service.stream_chat(prompt, use_rag=use_rag, table_name=table_name, file_ids=file_ids):
                if token:
                    yield f"data: {token}\n\n"
                    
            # 流式响应结束后的标记
            yield "data: [DONE]\n\n"
            
        return Response(stream_with_context(generate()), content_type='text/event-stream')
    except Exception as e:
        print(f"流式请求异常: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 添加一个用于调试的路由
@app.route('/debug_db')
def debug_db():
    try:
        result = {
            'sessions': [],
            'messages': {}
        }
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取所有会话
        cursor.execute("SELECT id, session_name, table_name, created_at FROM sessions ORDER BY id")
        sessions = cursor.fetchall()
        for session in sessions:
            session_info = {
                'id': session[0],
                'session_name': session[1],
                'table_name': session[2],
                'created_at': session[3]
            }
            result['sessions'].append(session_info)
            
            # 获取该会话的所有消息
            try:
                cursor.execute(f"SELECT id, sender, content, timestamp FROM {session[2]} ORDER BY id")
                messages = cursor.fetchall()
                formatted_messages = []
                for msg in messages:
                    formatted_messages.append({
                        'id': msg[0],
                        'sender': msg[1],
                        'content': msg[2],
                        'timestamp': msg[3]
                    })
                result['messages'][session[2]] = formatted_messages
            except Exception as e:
                result['messages'][session[2]] = {'error': str(e)}
        
        conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)})

# 获取或更新分块参数
@app.route(f'{API_PREFIX}/chunking_params', methods=['GET', 'POST'])
def handle_chunking_params():
    if request.method == 'POST':
        data = request.get_json()
        chunk_size = data.get('chunk_size')
        chunk_overlap = data.get('chunk_overlap')
        
        # 转换为整数（如果提供）
        if chunk_size:
            try:
                chunk_size = int(chunk_size)
            except ValueError:
                return jsonify({'error': '无效的块大小参数'}), 400
        
        if chunk_overlap:
            try:
                chunk_overlap = int(chunk_overlap)
            except ValueError:
                return jsonify({'error': '无效的块重叠参数'}), 400
        
        # 更新参数
        result = chat_service.document_service.update_chunking_params(
            chunk_size=chunk_size, 
            chunk_overlap=chunk_overlap
        )
        return jsonify(result)
    else:
        # 返回当前参数
        return jsonify({
            'chunk_size': chat_service.document_service.chunk_size,
            'chunk_overlap': chat_service.document_service.chunk_overlap
        })

@app.route(f'{API_PREFIX}/rebuild_vectorstore', methods=['POST'])
def rebuild_vectorstore():
    """重建向量存储库，重新处理所有已上传文档"""
    try:
        # 获取可选的确认参数
        data = request.get_json() or {}
        force_rebuild = data.get('force_rebuild', False)
        
        # 检查当前状态
        needs_rebuild = data.get('needs_rebuild', False)
        
        if not force_rebuild and not needs_rebuild:
            return jsonify({
                "status": "skipped",
                "message": "没有检测到需要重建的向量库，未执行重建。如果您确定要重建，请设置 force_rebuild=true"
            })
            
        # 重建向量库
        result = chat_service.rebuild_vectorstore()
        return jsonify(result)
    except Exception as e:
        print(f"重建向量库失败: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=9100)

