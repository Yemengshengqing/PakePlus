import os
from bs4 import SoupStrainer
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains.retrieval import create_retrieval_chain
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

KEY_V3 = os.getenv("KEY_V3")
KEY_ALI = os.getenv("KEY_ALI")
os.environ["USER_AGENT"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# llm模型
client = ChatOpenAI(model="qwen-max-latest",
                    base_url="https://api.vveai.com/v1",
                    # base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key=KEY_V3)
# 引入自己的嵌入模型
# from langchain_community.embeddings import DashScopeEmbeddings
# dash_embeddings = DashScopeEmbeddings(
#     dashscope_api_key=KEY_ALI, model="text-embedding-v3")

from langchain_openai import OpenAIEmbeddings
openai_embeddings = OpenAIEmbeddings(
    model="text-embedding-ada-002",
    openai_api_key=KEY_V3,
    # 添加第三方 API 端点配置
    base_url="https://api.vveai.com/v1"
)

# 获得文档，文档内容来自网页 bs4库
loader = WebBaseLoader(
    web_path=["https://www.news.cn/fortune/20250212/895ac6738b7b477db8d7f36c315aae22/c.html"],
    bs_kwargs=dict(
        parse_only=SoupStrainer(class_=("main-left left","title"))  # 直接使用 bs4 原生类
    )
)
docs = loader.load()
# print(len(docs))
# print(docs)

# 文档分割
splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
web_docs = splitter.split_documents(docs)
# for s in web_docs:
#     print(s)
#     print("----------------------------------------")


# 实例化向量空间
vector_store = Chroma.from_documents(
    documents=web_docs,
    embedding=openai_embeddings)
# # 检索器
retriever = vector_store.as_retriever()

#整合
system_prompt = """
您是问答任务的助理。使用以下检索到的上下文来回答问题。
如果你不知道答案，就说你不知道。
"""
prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system", system_prompt),
        ("assistant", "{context}"),
        ("human", "{input}")
    ]
)
# 创建 链
chain1 = create_stuff_documents_chain(llm=client, prompt=prompt_template)
chain2 = create_retrieval_chain(retriever, chain1)
# chain2 = create_retrieval_chain(chain1, retriever)

# 用大模型生成答案
resp = chain2.invoke({"input":"张成刚是谁？"})
# print(resp)
print(resp["answer"])

# 用大模型生成答案
resp = chain2.invoke({"input":"还有哪些人在报道中出现了？张成刚无需再列出"})
# print(resp)
print(resp["answer"])







