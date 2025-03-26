from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
import os

def setup_knowledge_base():
    loader = DirectoryLoader(
        'data/clinic_docs',
        glob="**/*.pdf",
        loader_cls=PyPDFLoader,
        silent_errors=True
    )
    
    print("Loading documents from:", os.path.abspath('data/clinic_docs'))
    try:
        docs = loader.load()
        print(f"Loaded {len(docs)} raw documents")
    except Exception as e:
        print(f"Error loading documents: {str(e)}")
        docs = []
    
    # Filter out empty documents
    # Debug document content
    print(f"Found {len(docs)} documents after filtering")
    for i, doc in enumerate(docs):
        print(f"Document {i+1} metadata: {doc.metadata}")
        print(f"Content preview: {doc.page_content[:100]}...")
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    splits = text_splitter.split_documents(docs)
    
    # Use OpenAI embeddings
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    # Verify document content
    if not splits:
        raise ValueError("No documents loaded - check PDF files in data/clinic_docs/")
    
    # Create vector store with validation
    vectorstore = FAISS.from_documents(
        documents=splits,
        embedding=embeddings
    )
    
    print(f"Created vector store with {len(vectorstore.index_to_docstore_id)} entries")
    
    return vectorstore.as_retriever()

# Initialize RAG retriever
clinic_retriever = setup_knowledge_base()