from langchain_community.chat_models import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from typing import TypedDict, List, Optional, Dict, Any
from datetime import datetime
import psycopg2
from dotenv import load_dotenv
import os
import logging
import re
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

class AgentState(TypedDict):
    messages: List[Dict[str, Any]]
    patient_id: Optional[str]
    doctor_id: Optional[str]
    slot: Optional[datetime]
    status: Optional[str]

def validate_ids(patient_id: str, doctor_id: str) -> bool:
    """Validate ID formats using regex patterns"""
    patient_pattern = r'^PAT-\d{4}$'
    doctor_pattern = r'^DR-\d{3}$'
    return (re.match(patient_pattern, patient_id) is not None and 
            re.match(doctor_pattern, doctor_id) is not None)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_db_connection():
    """Get database connection with retry logic"""
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            connect_timeout=5
        )
        conn.autocommit = False
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise

def book_appointment(state: AgentState) -> Dict[str, Any]:
    """Book appointment with validation and transaction management"""
    if not validate_ids(state['patient_id'], state['doctor_id']):
        return {
            "status": "error",
            "message": "Invalid ID format. Patient IDs must be PAT-XXXX, Doctor IDs DR-XXX"
        }

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO appointments 
                (patient_id, doctor_id, slot, status)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (
                state['patient_id'], 
                state['doctor_id'], 
                state['slot'],
                state.get('status', 'pending')  # Configurable status
            ))
            appointment_id = cur.fetchone()[0]
            conn.commit()
        
        return {
            "status": "success",
            "appointment_id": appointment_id,
            "message": f"Appointment {appointment_id} confirmed"
        }
    except Exception as e:
        logger.error(f"Booking failed: {e}")
        if conn:
            conn.rollback()
        return {
            "status": "error",
            "message": f"Booking failed: {str(e)}"
        }
    finally:
        if conn:
            conn.close()

# Initialize components with rate limiting
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0.7,
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=3,
    request_timeout=30
)

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a medical appointment assistant. Help with:
     - Scheduling appointments
     - Answering clinic questions
     - Providing medical information
     
     Be professional and helpful.
     Current patient: {patient_id}"""),
    ("user", "{input}")
])

chain = prompt | llm | StrOutputParser()

def handle_message(state: AgentState) -> Dict[str, Any]:
    """Process message with comprehensive error handling"""
    try:
        if not state.get('messages') or not state['messages'][-1]['content']:
            raise ValueError("Empty message content")
            
        response = chain.invoke({
            "input": state['messages'][-1]['content'],
            "patient_id": state.get('patient_id', 'new patient')
        })
        
        if "book" in response.lower():
            booking_result = book_appointment(state)
            response += f"\n\n{booking_result['message']}"
            
        return {"response": response}
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return {"response": "Sorry, we encountered an error. Please try again later."}

if __name__ == "__main__":
    state = {
        "messages": [{"content": "I need to book a checkup"}],
        "patient_id": "PAT-1234",
        "doctor_id": "DR-456",
        "slot": datetime(2025, 3, 28, 14, 0)
    }
    result = handle_message(state)
    print("Assistant:", result["response"])