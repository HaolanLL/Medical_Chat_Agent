from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Optional, List, Any
import os
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

class RAGConfig:
    """Configuration for RAG setup"""
    def __init__(self):
        self.data_dir = os.getenv("DATA_DIR", "data/clinic_docs")
        self.chunk_size = int(os.getenv("CHUNK_SIZE", 1000))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", 200))
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        
        if not os.path.exists(self.data_dir):
            raise ValueError(f"Data directory not found: {self.data_dir}")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def load_documents(config: RAGConfig) -> List[Any]:
    """Load and validate documents with retry logic"""
    try:
        loader = DirectoryLoader(
            config.data_dir,
            glob="**/*.pdf",
            loader_cls=PyPDFLoader,
            silent_errors=True
        )
        docs = loader.load()
        
        if not docs:
            logger.warning(f"No documents found in {config.data_dir}")
            return []
            
        # Filter and validate documents
        valid_docs = []
        for doc in docs:
            if doc.page_content.strip():
                valid_docs.append(doc)
            else:
                logger.warning(f"Empty document: {doc.metadata.get('source')}")
                
        logger.info(f"Loaded {len(valid_docs)} valid documents")
        return valid_docs
        
    except Exception as e:
        logger.error(f"Document loading failed: {str(e)}")
        raise

def setup_knowledge_base() -> Any:
    """Setup RAG knowledge base with validation"""
    config = RAGConfig()
    
    try:
        # Load and split documents
        docs = load_documents(config)
        if not docs:
            raise ValueError("No valid documents available for processing")
            
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap
        )
        splits = text_splitter.split_documents(docs)
        
        # Initialize embeddings with retry
        @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
        def get_embeddings():
            return OpenAIEmbeddings(model=config.embedding_model)
            
        embeddings = get_embeddings()
        
        # Create vector store
        vectorstore = FAISS.from_documents(
            documents=splits,
            embedding=embeddings
        )
        
        logger.info(f"Created vector store with {len(vectorstore.index_to_docstore_id)} entries")
        return vectorstore.as_retriever()
        
    except Exception as e:
        logger.error(f"Knowledge base setup failed: {str(e)}")
        raise

# Initialize RAG retriever with error handling
try:
    clinic_retriever = setup_knowledge_base()
except Exception as e:
    logger.critical(f"Failed to initialize RAG system: {str(e)}")
    clinic_retriever = None