import os
from typing import List, Dict, Any
import json
import uuid
import shutil
from PyPDF2 import PdfReader
from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.embeddings import Embeddings

class DocumentService:
    """
    文档服务类，负责处理PDF文件、切分文本、创建向量存储和检索
    """
    
    def __init__(self, 
                 embedding_model_name: str = "deepseek-r1:8b",
                 embedding_base_url: str = "http://localhost:11434",
                 chunk_size: int = 500, 
                 chunk_overlap: int = 100,
                 persist_directory: str = "db/chroma"):
        """
        初始化文档服务
        
        参数:
            embedding_model_name: 嵌入模型名称
            embedding_base_url: 嵌入API的基础URL
            chunk_size: 文本块大小
            chunk_overlap: 文本块重叠大小
            persist_directory: 向量数据库持久化目录
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.persist_directory = persist_directory
        self.file_info_path = "db/file_info.json"
        self.uploaded_files = {}  # 存储已上传文件信息
        self.current_embedding_dimension = 0  # 当前嵌入向量的维度
        
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(self.file_info_path), exist_ok=True)
        os.makedirs(self.persist_directory, exist_ok=True)
        
        # 初始化嵌入模型
        self.embedding = OllamaEmbeddings(
            model=embedding_model_name, 
            base_url=embedding_base_url
        )
        
        # 创建或加载向量数据库
        self._load_or_create_vectorstore()
        
        # 加载已上传文件信息
        self.load_file_info()
    
    def _load_or_create_vectorstore(self):
        """加载或创建向量存储库"""
        try:
            self.vectorstore = Chroma(
                persist_directory=self.persist_directory, 
                embedding_function=self.embedding
            )
            print(f"已加载向量数据库，共有{self.vectorstore._collection.count()}条记录")
            
            # 如果有记录，获取当前维度
            if self.vectorstore._collection.count() > 0:
                try:
                    # 获取现有向量的维度
                    self.current_embedding_dimension = self.vectorstore._collection._embedding_function().dimensionality
                    print(f"当前向量维度: {self.current_embedding_dimension}")
                except Exception as e:
                    print(f"无法确定向量维度: {e}")
                    self.current_embedding_dimension = 0
            
        except Exception as e:
            print(f"加载向量数据库失败，将创建新的向量数据库: {e}")
            self.vectorstore = Chroma(
                persist_directory=self.persist_directory, 
                embedding_function=self.embedding
            )
            self.current_embedding_dimension = 0
    
    def get_embedding_dimension(self, embedding_model):
        """
        获取嵌入模型的向量维度
        
        参数:
            embedding_model: 嵌入模型实例
            
        返回:
            向量维度
        """
        try:
            # 通过嵌入一个简单的文本来确定维度
            test_embedding = embedding_model.embed_query("测试文本")
            return len(test_embedding)
        except Exception as e:
            print(f"无法获取嵌入向量维度: {e}")
            return 0
    
    def update_embedding_model(self, model_name: str = None, base_url: str = None, embedding_model: Embeddings = None):
        """
        更新嵌入模型配置
        
        参数:
            model_name: 新的模型名称
            base_url: 新的API基础URL
            embedding_model: 已实例化的嵌入模型对象
            
        返回:
            更新状态，包括是否需要重建向量库
        """
        old_embedding = self.embedding
        
        # 更新嵌入模型
        if embedding_model:
            # 如果提供了嵌入模型实例，直接使用
            self.embedding = embedding_model
        elif model_name or base_url:
            # 否则使用提供的参数创建新的OllamaEmbeddings实例
            self.embedding = OllamaEmbeddings(
                model=model_name if model_name else self.embedding.client.model,
                base_url=base_url if base_url else self.embedding.client.base_url
            )
            
        # 检查新模型的维度
        new_dimension = self.get_embedding_dimension(self.embedding)
        
        # 判断是否需要重建向量库
        needs_rebuild = False
        if self.vectorstore._collection.count() > 0 and self.current_embedding_dimension > 0:
            if new_dimension != self.current_embedding_dimension:
                print(f"嵌入向量维度变化: {self.current_embedding_dimension} -> {new_dimension}，需要重建向量库")
                needs_rebuild = True
            
        update_result = {
            "old_dimension": self.current_embedding_dimension,
            "new_dimension": new_dimension,
            "needs_rebuild": needs_rebuild,
            "document_count": self.vectorstore._collection.count()
        }
        
        if needs_rebuild:
            # 如果维度不同，先恢复旧的嵌入模型，让调用者决定是否重建
            self.embedding = old_embedding
            return update_result
            
        # 维度相同或没有文档，直接更新向量存储
        try:
            self._load_or_create_vectorstore()
            self.current_embedding_dimension = new_dimension
            update_result["success"] = True
        except Exception as e:
            print(f"更新向量存储失败: {e}")
            update_result["success"] = False
            update_result["error"] = str(e)
            # 恢复原来的嵌入模型
            self.embedding = old_embedding
            self._load_or_create_vectorstore()
            
        return update_result
    
    def rebuild_vectorstore(self):
        """
        重建向量存储库，重新处理所有已上传文档
        
        返回:
            重建结果
        """
        try:
            # 备份原始文件信息
            all_files = self.uploaded_files.copy()
            
            if not all_files:
                return {"status": "no_files", "message": "没有找到任何文件信息，无需重建向量库"}
                
            # 删除现有向量库
            if os.path.exists(self.persist_directory):
                shutil.rmtree(self.persist_directory)
                os.makedirs(self.persist_directory, exist_ok=True)
                
            # 重新创建向量库
            self.vectorstore = Chroma(
                persist_directory=self.persist_directory, 
                embedding_function=self.embedding
            )
            
            # 获取新的嵌入维度
            self.current_embedding_dimension = self.get_embedding_dimension(self.embedding)
            
            # 重新处理所有文档
            processed_files = 0
            failed_files = []
            
            for file_id, file_info in all_files.items():
                file_path = file_info.get('file_path')
                file_name = file_info.get('file_name')
                chunk_size = file_info.get('chunk_size', self.chunk_size)
                chunk_overlap = file_info.get('chunk_overlap', self.chunk_overlap)
                
                if os.path.exists(file_path):
                    try:
                        # 提取文本
                        pdf_reader = PdfReader(file_path)
                        text = ""
                        for page_num in range(len(pdf_reader.pages)):
                            page = pdf_reader.pages[page_num]
                            text += page.extract_text()
                        
                        # 分割文本
                        text_splitter = RecursiveCharacterTextSplitter(
                            chunk_size=chunk_size,
                            chunk_overlap=chunk_overlap
                        )
                        
                        chunks = text_splitter.split_text(text)
                        documents = [Document(page_content=chunk, metadata={"source": file_name, "file_id": file_id}) for chunk in chunks]
                        
                        # 添加到向量存储
                        self.vectorstore.add_documents(documents)
                        
                        # 更新文件信息
                        self.uploaded_files[file_id] = {
                            "file_name": file_name,
                            "file_path": file_path,
                            "chunk_count": len(chunks),
                            "chunk_size": chunk_size,
                            "chunk_overlap": chunk_overlap,
                            "total_tokens": sum(len(chunk.split()) for chunk in chunks)
                        }
                        
                        processed_files += 1
                    except Exception as e:
                        print(f"重新处理文件失败 {file_name}: {e}")
                        failed_files.append({"file_id": file_id, "file_name": file_name, "error": str(e)})
                else:
                    print(f"文件不存在，跳过处理: {file_path}")
                    failed_files.append({"file_id": file_id, "file_name": file_name, "error": "文件不存在"})
            
            # 保存更新后的文件信息
            self.save_file_info()
            
            return {
                "status": "success",
                "processed_files": processed_files,
                "failed_files": failed_files,
                "total_files": len(all_files),
                "new_dimension": self.current_embedding_dimension,
                "document_count": self.vectorstore._collection.count()
            }
            
        except Exception as e:
            print(f"重建向量库失败: {e}")
            return {
                "status": "error",
                "message": f"重建向量库失败: {str(e)}"
            }
    
    def update_chunking_params(self, chunk_size: int = None, chunk_overlap: int = None):
        """
        更新文本分块参数
        
        参数:
            chunk_size: 新的文本块大小
            chunk_overlap: 新的文本块重叠大小
            
        返回:
            更新后的参数字典
        """
        if chunk_size is not None:
            self.chunk_size = max(100, min(5000, chunk_size))  # 限制在合理范围内
        
        if chunk_overlap is not None:
            # 确保重叠大小不超过块大小的一半
            self.chunk_overlap = max(0, min(self.chunk_size // 2, chunk_overlap))
        
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap
        }
    
    def process_pdf(self, file_path: str, file_name: str, custom_chunk_size: int = None, custom_chunk_overlap: int = None) -> Dict[str, Any]:
        """
        处理PDF文件，提取文本、分割、创建向量存储
        
        参数:
            file_path: PDF文件路径
            file_name: 文件名称
            custom_chunk_size: 自定义的文本块大小，如果为None则使用当前设置
            custom_chunk_overlap: 自定义的文本块重叠大小，如果为None则使用当前设置
            
        返回:
            包含处理结果的字典
        """
        try:
            # 生成唯一文件ID
            file_id = str(uuid.uuid4())
            
            # 提取文本
            pdf_reader = PdfReader(file_path)
            text = ""
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text()
            
            # 使用自定义参数或默认参数
            chunk_size = custom_chunk_size if custom_chunk_size is not None else self.chunk_size
            chunk_overlap = custom_chunk_overlap if custom_chunk_overlap is not None else self.chunk_overlap
            
            # 分割文本
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
            chunks = text_splitter.split_text(text)
            documents = [Document(page_content=chunk, metadata={"source": file_name, "file_id": file_id}) for chunk in chunks]
            
            # 添加到向量存储
            self.vectorstore.add_documents(documents)
            
            # 如果之前没有文档，获取当前维度
            if self.current_embedding_dimension == 0:
                self.current_embedding_dimension = self.get_embedding_dimension(self.embedding)
                print(f"设置当前向量维度为: {self.current_embedding_dimension}")
            
            # 记录文件信息
            self.uploaded_files[file_id] = {
                "file_name": file_name,
                "file_path": file_path,
                "chunk_count": len(chunks),
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "total_tokens": sum(len(chunk.split()) for chunk in chunks)
            }
            
            # 保存文件信息
            self.save_file_info()
            
            return {
                "status": "success",
                "file_id": file_id,
                "file_name": file_name,
                "chunk_count": len(chunks),
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "message": f"成功处理文档 {file_name}，分割为 {len(chunks)} 个文本块"
            }
            
        except Exception as e:
            print(f"处理PDF文件失败: {e}")
            return {
                "status": "error",
                "message": f"处理PDF文件失败: {str(e)}"
            }
    
    def get_relevant_documents(self, query: str, top_k: int = 4, file_ids: List[str] = None) -> List[Document]:
        """
        检索与查询相关的文档片段
        
        参数:
            query: 查询文本
            top_k: 返回的文档数量
            file_ids: 要检索的文档ID列表，如果为None则从所有文档中检索
            
        返回:
            相关文档列表
        """
        if not self.vectorstore._collection.count():
            return []
        
        # 如果指定了文档ID，则只从这些文档中检索
        if file_ids and len(file_ids) > 0:
            try:
                return self.vectorstore.similarity_search(
                    query, 
                    k=top_k,
                    filter={"file_id": {"$in": file_ids}}
                )
            except Exception as e:
                print(f"检索指定文档失败: {e}，将回退到全库检索")
                return self.vectorstore.similarity_search(query, k=top_k)
        
        # 从所有文档中检索
        return self.vectorstore.similarity_search(query, k=top_k)
    
    def get_uploaded_files(self) -> Dict[str, Dict[str, Any]]:
        """获取已上传的文件列表"""
        return self.uploaded_files
        
    def delete_file(self, file_id: str) -> Dict[str, Any]:
        """
        删除指定的文件及其向量
        
        参数:
            file_id: 文件ID
            
        返回:
            操作结果
        """
        try:
            if file_id not in self.uploaded_files:
                return {
                    "status": "error",
                    "message": f"文件ID {file_id} 不存在"
                }
            
            # 从向量存储中删除相关文档
            try:
                # 首先查询与该文件ID关联的所有文档
                results = self.vectorstore.get(where={"file_id": file_id})
                if results and 'ids' in results and results['ids']:
                    # 使用ID列表删除文档
                    self.vectorstore.delete(ids=results['ids'])
                else:
                    print(f"未找到与文件ID {file_id} 关联的向量存储记录")
            except Exception as ve:
                # 如果上面的方法失败，尝试替代方案
                print(f"删除向量存储记录失败: {ve}，尝试替代方案...")
                try:
                    # 尝试兼容不同版本的API
                    self.vectorstore._collection.delete(where={"file_id": file_id})
                except Exception as ve2:
                    print(f"替代方案也失败: {ve2}")
                    # 继续处理，至少删除文件记录
            
            # 从已上传文件记录中删除
            file_info = self.uploaded_files.pop(file_id)
            
            # 如果是物理文件，尝试删除
            if 'file_path' in file_info and os.path.exists(file_info['file_path']):
                try:
                    os.remove(file_info['file_path'])
                    print(f"已删除物理文件: {file_info['file_path']}")
                except Exception as fe:
                    print(f"删除物理文件失败: {fe}")
            
            # 保存文件信息
            self.save_file_info()
            
            return {
                "status": "success",
                "message": f"成功删除文件 {file_info['file_name']}"
            }
        except Exception as e:
            print(f"删除文件失败: {str(e)}")
            return {
                "status": "error",
                "message": f"删除文件失败: {str(e)}"
            }
    
    def save_file_info(self):
        """将已上传文件信息保存到磁盘"""
        try:
            # 使用JSON格式存储文件信息
            with open(self.file_info_path, 'w', encoding='utf-8') as f:
                json.dump(self.uploaded_files, f, ensure_ascii=False, indent=2)
            print(f"已保存文件信息到 {self.file_info_path}")
        except Exception as e:
            print(f"保存文件信息失败: {e}")
    
    def load_file_info(self):
        """从磁盘加载已上传的文件信息"""
        try:
            if os.path.exists(self.file_info_path):
                with open(self.file_info_path, 'r', encoding='utf-8') as f:
                    self.uploaded_files = json.load(f)
                print(f"已加载 {len(self.uploaded_files)} 个文件信息")
            else:
                print("文件信息文件不存在，将创建新的文件信息")
                self.uploaded_files = {}
        except Exception as e:
            print(f"加载文件信息失败: {e}")
            self.uploaded_files = {} 