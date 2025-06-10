import sqlite3
from datetime import datetime
from models import Message

class MessageService:
    """
    消息服务类，负责消息的存储和检索
    对应Java版本的IMessageService和MessageServiceImpl
    """
    
    def __init__(self, db_path='messages.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self, table_name="messages"):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        ''')
        conn.commit()
        conn.close()
    
    def save(self, message, table_name="messages"):
        """保存消息到数据库"""
        # 确保表存在
        self._init_db(table_name)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if message.id is None:
            # 插入新消息
            cursor.execute(
                f"INSERT INTO {table_name} (sender, content, timestamp) VALUES (?, ?, ?)",
                (message.sender, message.content, message.created_at.strftime("%Y-%m-%d %H:%M:%S"))
            )
            message.id = cursor.lastrowid
        else:
            # 更新现有消息
            cursor.execute(
                f"UPDATE {table_name} SET sender=?, content=?, timestamp=? WHERE id=?",
                (message.sender, message.content, message.created_at.strftime("%Y-%m-%d %H:%M:%S"), message.id)
            )
        
        conn.commit()
        conn.close()
        return message
    
    def get_by_id(self, message_id, table_name="messages"):
        """通过ID获取消息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT id, sender, content, timestamp FROM {table_name} WHERE id=?", (message_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Message(
                id=row[0],
                sender=row[1],
                content=row[2],
                created_at=datetime.strptime(row[3], "%Y-%m-%d %H:%M:%S")
            )
        return None
    
    def list(self, table_name="messages"):
        """获取所有消息"""
        # 确保表存在
        self._init_db(table_name)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT id, sender, content, timestamp FROM {table_name} ORDER BY id")
        
        messages = []
        for row in cursor.fetchall():
            messages.append(Message(
                id=row[0],
                sender=row[1],
                content=row[2],
                created_at=datetime.strptime(row[3], "%Y-%m-%d %H:%M:%S")
            ))
        
        conn.close()
        return messages
    
    def delete(self, message_id, table_name="messages"):
        """删除消息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {table_name} WHERE id=?", (message_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0 