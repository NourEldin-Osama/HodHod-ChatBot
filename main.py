import os
import shutil
from typing import List

from fastapi import FastAPI, HTTPException, UploadFile, File
from langchain.agents import AgentType, Tool, initialize_agent, load_tools
from langchain.chains import RetrievalQA
from langchain.chat_models import AzureChatOpenAI
from langchain.document_loaders import DirectoryLoader
from langchain.embeddings import OpenAIEmbeddings
from langchain.memory import ConversationBufferMemory
from langchain.schema import HumanMessage
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Chroma
from pydantic import BaseModel

from config import persist_directory, azure_embeddings_deployment_name

model = AzureChatOpenAI(
    deployment_name=os.getenv("DEPLOYMENT_NAME"),
)
embedding_model = OpenAIEmbeddings(deployment=azure_embeddings_deployment_name)
tools = load_tools(["serpapi", "llm-math"], llm=model)
os.makedirs("Documents", exist_ok=True)


def create_vdb_search_tool():
    # Print number of txt files in directory
    loader = DirectoryLoader("", glob="Documents/*.*")
    documents = loader.load()

    # Splitting the text into chunks
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=100)
    texts = text_splitter.split_documents(documents)

    print(
        f"Number of Documents = {len(documents)}",
        f"Number of Chunks = {len(texts)}",
        sep="\n",
    )

    vector_db = Chroma.from_documents(
        documents=texts, embedding=embedding_model, persist_directory=persist_directory
    )

    vector_db_search = RetrievalQA.from_chain_type(
        llm=model,
        chain_type="stuff",
        retriever=vector_db.as_retriever(),
        verbose=True,
        return_source_documents=True,
        input_key="question",
    )

    vector_db_search_tool = Tool(
        name="Obeikan QA System",
        func=lambda query: vector_db_search({"question": query}),
        description="useful for when you need to answer questions about the Obeikan. Input should be a fully formed question. Output will be include the source document.",
    )
    return vector_db_search_tool


tools.append(create_vdb_search_tool())

# Define the API
app = FastAPI()


class Message(BaseModel):
    id: int
    msg: str


dic = {}


@app.post("/new_chat")
def new_chat():
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    agent_chain = initialize_agent(
        tools,
        model,
        agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
        verbose=True,
        memory=memory,
    )
    new_id = len(dic) + 1
    dic[new_id] = agent_chain
    return {"id": new_id}


@app.post("/new_msg")
def new_msg(input_msg: Message):
    agent_chain = dic[input_msg.id]
    response = agent_chain.run(input_msg.msg)
    return {"response": f"{response}"}


# Add a post method to the API that return a list of all files in the Documents folder using os.listdir()
@app.post("/view_files")
def view_files():
    return {"files": os.listdir("Documents")}


@app.post("/upload_files")
async def upload_files(files: List[UploadFile] = File(...)):
    files_name = [file.filename for file in files]
    for file in files:
        with open(f"Documents/{file.filename}", "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    create_vdb_search_tool()
    global tools
    tools[-1] = create_vdb_search_tool()

    return {"detail": f"Files {', '.join(files_name)} uploaded successfully"}


# Add a post method to the API that delete file from the Documents folder using os.remove()
@app.post("/delete_files")
def delete_files(file_name: str):
    if file_name in os.listdir("Documents"):
        os.remove(f"Documents/{file_name}")
        create_vdb_search_tool()
        global tools
        tools[-1] = create_vdb_search_tool()
        return {"detail": f"File {file_name} deleted successfully"}
    return {"detail": f"File {file_name} not found"}
