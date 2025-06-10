from langchain_ollama import OllamaLLM
from langchain_openai import ChatOpenAI
from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from datetime import datetime
from typing import Optional, List
from models import Message
from db_service import MessageService
from document_service import DocumentService

class ChatService:
    """
    聊天服务类，使用LangChain处理聊天功能
    支持Ollama和任何符合OpenAI规范的API
    """
    
    def __init__(self, 
                 model_name="llama3", 
                 api_base_url="http://localhost:11434", 
                 api_type="ollama",
                 api_key=None,
                 embedding_model=None,
                 db_path='messages.db'):
        """
        初始化聊天服务
        
        参数:
            model_name: 模型名称，默认为llama3
            api_base_url: API的基础URL，默认为http://localhost:11434
            api_type: API类型，可选值为 'ollama' 或 'openai'，默认为ollama
            api_key: API密钥，仅在api_type为'openai'时需要
            embedding_model: 嵌入模型名称，如果为None则使用model_name
            db_path: 数据库文件路径，默认为messages.db
        """
        self.model_name = model_name
        self.api_base_url = api_base_url
        self.api_type = api_type
        self.api_key = api_key
        self.embedding_model = embedding_model or model_name
        
        # 根据API类型初始化模型
        if api_type == 'ollama':
            self.model = OllamaLLM(model=model_name, base_url=api_base_url)
        elif api_type == 'openai':
            self.model = ChatOpenAI(
                model_name=model_name,
                openai_api_key=api_key,
                openai_api_base=api_base_url,
                streaming=True
            )
        else:
            raise ValueError(f"不支持的API类型: {api_type}，支持的类型有: ollama, openai")
        
        self.message_service = MessageService(db_path)
        
        # 初始化文档服务
        self.document_service = DocumentService(
            embedding_model_name=self.embedding_model,
            embedding_base_url=self.api_base_url
        )
        
        # 定义RAG提示模板
        self.rag_template = ChatPromptTemplate.from_template(
            """你是一个知识丰富的AI助手，具备强大的理解能力和专业知识。
            
            请回答以下问题，并利用提供的上下文信息：
            
            问题: {question}
            
            上下文信息:
            {context}
            
            如果上下文中没有足够信息回答问题，请使用你自己的知识进行回答。
            回答要详细、准确，如有需要可以使用层次结构和例子来解释。
            如果引用了上下文中的内容，请在回答中明确指出"根据文档..."。
            """
        )
    
    def save_message(self, sender, content, table_name="messages"):
        """
        保存消息
        """
        message = Message(
            sender=sender,
            content=content,
            created_at=datetime.now()
        )
        return self.message_service.save(message, table_name)
    
    def get_messages(self, table_name="messages"):
        """
        获取所有消息
        """
        return self.message_service.list(table_name)
    
    def chat(self, prompt, callback=None, use_rag=False, table_name="messages"):
        """
        处理聊天请求
        
        参数:
            prompt: 用户输入
            callback: 回调函数，用于流式处理
            use_rag: 是否使用文档检索增强
            table_name: 消息表名
        """
        # 保存用户消息
        self.save_message("user", prompt, table_name)
        
        # 创建响应收集器
        class ResponseCollector(BaseCallbackHandler):
            def __init__(self):
                self.response = ""
                self.external_callback = callback
            
            def on_llm_new_token(self, token, **kwargs):
                self.response += token
                if self.external_callback:
                    self.external_callback(token)
        
        # 创建回调处理器
        collector = ResponseCollector()
        
        response_content = ""
        
        if use_rag:
            # 检索相关文档
            retrieved_docs = self.document_service.get_relevant_documents(prompt)
            
            if retrieved_docs:
                # 格式化检索到的文档
                context = "\n\n".join([f"文档段落 {i+1}:\n{doc.page_content}\n(来源: {doc.metadata['source']})" 
                                      for i, doc in enumerate(retrieved_docs)])
                
                # 创建RAG链
                rag_chain = LLMChain(
                    llm=self.model,
                    prompt=self.rag_template
                )
                
                # 使用RAG链生成响应
                if self.api_type == 'ollama':
                    response = rag_chain.invoke({"question": prompt, "context": context}, callbacks=[collector])
                    if not collector.response:  # 如果回调没有收集到响应
                        collector.response = response["text"]
                else:  # openai
                    response = rag_chain.invoke({"question": prompt, "context": context}, callbacks=[collector])
                    if not collector.response:  # 如果回调没有收集到响应
                        collector.response = response["text"]
                
                # 添加思考过程(显示检索到的文档) - 只在后台保存，不在前端显示
                thinking = f"<think>检索到 {len(retrieved_docs)} 个相关文档片段：\n\n{context}</think>"
                response_content = thinking + collector.response
            else:
                # 如果没有检索到文档，使用普通聊天
                if self.api_type == 'ollama':
                    self.model.generate([prompt], callbacks=[collector])
                else:  # openai
                    response = self.model.invoke(prompt, callbacks=[collector])
                    if not collector.response:  # 如果回调没有收集到响应
                        collector.response = response.content
                
                response_content = collector.response
        else:
            # 普通聊天处理逻辑
            if self.api_type == 'ollama':
                self.model.generate([prompt], callbacks=[collector])
            else:  # openai
                response = self.model.invoke(prompt, callbacks=[collector])
                if not collector.response:  # 如果回调没有收集到响应
                    collector.response = response.content
            
            response_content = collector.response
        
        # 保存AI响应
        self.save_message("bot", response_content, table_name)
        
        return response_content
    
    def stream_chat(self, prompt, use_rag=False, table_name="messages", file_ids=None):
        """
        流式处理聊天请求
        
        参数:
            prompt: 用户输入
            use_rag: 是否使用文档检索增强
            table_name: 消息表名
            file_ids: 要使用的文档ID列表，如果为None或空列表则使用所有文档
        """
        # 保存用户消息
        self.save_message("user", prompt, table_name)
        
        full_response = ""
        
        # 定义回调函数来收集完整响应
        def collect_response(token):
            nonlocal full_response
            full_response += token
        
        if use_rag:
            # 检索相关文档
            retrieved_docs = self.document_service.get_relevant_documents(prompt, file_ids=file_ids)
            
            if retrieved_docs:
                # 格式化检索到的文档
                context = "\n\n".join([f"文档段落 {i+1}:\n{doc.page_content}\n(来源: {doc.metadata['source']})" 
                                      for i, doc in enumerate(retrieved_docs)])
                
                # 添加思考过程(显示检索到的文档) - 不发送给前端，仅用于后台
                thinking = f"<think>检索到 {len(retrieved_docs)} 个相关文档片段：\n\n{context}</think>"
                # 不再输出thinking到前端
                # yield thinking
                # collect_response(thinking)
                
                # 记录到完整回复中，但不发送到前端
                collect_response(thinking)
                
                # 创建RAG链
                rag_chain = LLMChain(
                    llm=self.model,
                    prompt=self.rag_template
                )
                
                # 使用RAG链生成流式响应
                if self.api_type == 'ollama':
                    for chunk in rag_chain.stream({"question": prompt, "context": context}):
                        token = chunk["text"] if "text" in chunk else str(chunk)
                        yield token
                        collect_response(token)
                else:  # openai
                    for chunk in rag_chain.stream({"question": prompt, "context": context}):
                        token = chunk["text"] if "text" in chunk else str(chunk)
                        yield token
                        collect_response(token)
            else:
                # 没有检索到文档，使用普通流式处理
                if self.api_type == 'ollama':
                    for chunk in self.model.stream(prompt):
                        yield chunk
                        collect_response(chunk)
                else:  # openai
                    for chunk in self.model.stream(prompt):
                        token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                        yield token
                        collect_response(token)
        else:
            # 普通流式处理
            if self.api_type == 'ollama':
                for chunk in self.model.stream(prompt):
                    yield chunk
                    collect_response(chunk)
            else:  # openai
                for chunk in self.model.stream(prompt):
                    token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    yield token
                    collect_response(token)
        
        # 保存完整的AI响应
        self.save_message("bot", full_response, table_name)
    
    def update_model(self, model_name=None, api_base_url=None, api_type=None, api_key=None, embedding_model=None):
        """
        更新模型配置
        
        参数:
            model_name: 新的模型名称，如果为None则保持不变
            api_base_url: 新的API基础URL，如果为None则保持不变
            api_type: 新的API类型，如果为None则保持不变
            api_key: 新的API密钥，如果为None则保持不变
            embedding_model: 新的嵌入模型名称，如果为None则保持不变
            
        返回:
            包含更新结果的字典，如果需要重建向量库会包含相关信息
        """
        result = {
            "model_updated": False,
            "embedding_updated": False,
            "needs_rebuild": False
        }
        
        if model_name:
            self.model_name = model_name
        
        if api_base_url:
            self.api_base_url = api_base_url
        
        if api_type:
            self.api_type = api_type
        
        if api_key:
            self.api_key = api_key
            
        if embedding_model:
            self.embedding_model = embedding_model
        
        # 重新初始化模型
        if self.api_type == 'ollama':
            self.model = OllamaLLM(model=self.model_name, base_url=self.api_base_url)
        elif self.api_type == 'openai':
            self.model = ChatOpenAI(
                model_name=self.model_name,
                openai_api_key=self.api_key,
                openai_api_base=self.api_base_url,
                streaming=True
            )
        
        result["model_updated"] = True
        
        # 更新嵌入模型 - 根据API类型选择适当的嵌入模型
        if self.api_type == 'ollama':
            # 使用Ollama的嵌入模型
            from langchain_ollama import OllamaEmbeddings
            embedding_model_instance = OllamaEmbeddings(
                model=self.embedding_model, 
                base_url=self.api_base_url
            )
        elif self.api_type == 'openai':
            # 使用OpenAI的嵌入模型
            from langchain_openai import OpenAIEmbeddings
            embedding_model_instance = OpenAIEmbeddings(
                model=self.embedding_model,
                openai_api_key=self.api_key,
                openai_api_base=self.api_base_url
            )
        else:
            # 默认使用Ollama嵌入模型
            from langchain_ollama import OllamaEmbeddings
            embedding_model_instance = OllamaEmbeddings(
                model=self.embedding_model, 
                base_url=self.api_base_url
            )
            
        # 更新文档服务的嵌入模型，这将检测维度变化
        embedding_update_result = self.document_service.update_embedding_model(embedding_model=embedding_model_instance)
        result.update(embedding_update_result)
        result["embedding_updated"] = True
        
        return {
            "model_name": self.model_name,
            "api_base_url": self.api_base_url,
            "api_type": self.api_type,
            "api_key": self.api_key and "******",  # 隐藏实际密钥
            "embedding_model": self.embedding_model,
            **result
        }
    
    def rebuild_vectorstore(self):
        """
        重建向量存储
        
        返回:
            重建结果
        """
        return self.document_service.rebuild_vectorstore() 