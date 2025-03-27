from langchain_openai import ChatOpenAI
from langgraph.graph import Graph
from langgraph.prebuilt import chat_agent_executor
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

def validate_config():
    """Validate required environment variables"""
    required_vars = [
        "DB_NAME", "DB_USER",
        "DB_PASSWORD", "DB_HOST",
        "OPENAI_API_KEY"
    ]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {missing}")

load_dotenv()
validate_config()

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

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent prompt injection"""
    return re.sub(r'[^\w\s.,?!-]', '', text)[:500]

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a medical appointment assistant. Help with:
     - Scheduling appointments (verify availability first)
     - Answering clinic questions (hours, services, policies)
     - Providing general medical information (non-diagnostic)
     
     Rules:
     1. Always verify patient and doctor IDs
     2. Never provide medical diagnoses
     3. Maintain professional tone
     4. Confirm details before booking
     
     Current patient: {patient_id}"""),
    ("user", "{input}")
])

# Create LangGraph workflow
workflow = Graph()
workflow.add_node("agent", chat_agent_executor.create_agent(llm, prompt))
workflow.add_node("book_appointment", book_appointment)
workflow.set_entry_point("agent")
workflow.add_conditional_edges(
    "agent",
    lambda x: "book_appointment" if "book" in x.get("output", "").lower() else "end",
)
workflow.add_edge("book_appointment", "agent")
app = workflow.compile()

def handle_message(state: AgentState) -> Dict[str, Any]:
    """Process message using LangGraph workflow"""
    try:
        if not state.get('messages') or not state['messages'][-1]['content']:
            raise ValueError("Empty message content")
        
        sanitized_input = sanitize_input(state['messages'][-1]['content'])
        state['input'] = sanitized_input
        
        result = app.invoke(state)
        return {"response": result.get("output", result)}
        
        if "book" in response.lower():
            booking_result = book_appointment(state)
            response += f"\n\n{booking_result['message']}"
            
        return {"response": response}
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return {"response": "Sorry, we encountered an error. Please try again later."}

if __name__ == "__main__":
    import argparse
    from datetime import datetime
    
    parser = argparse.ArgumentParser(
        description="Medical Appointment Chatbot CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--patient-id",
        required=True,
        help="Patient ID in PAT-XXXX format"
    )
    parser.add_argument(
        "--doctor-id",
        required=True,
        help="Doctor ID in DR-XXX format"
    )
    parser.add_argument(
        "--message",
        required=True,
        help="Appointment request message"
    )
    parser.add_argument(
        "--slot",
        help="Optional appointment slot (YYYY-MM-DD HH:MM)"
    )
    
    args = parser.parse_args()
    
    if not validate_ids(args.patient_id, args.doctor_id):
        print("Error: Invalid ID format")
        exit(1)
        
    slot = None
    if args.slot:
        try:
            slot = datetime.strptime(args.slot, "%Y-%m-%d %H:%M")
        except ValueError:
            print("Error: Invalid slot format. Use YYYY-MM-DD HH:MM")
            exit(1)

    state = {
        "messages": [{"content": args.message}],
        "patient_id": args.patient_id,
        "doctor_id": args.doctor_id,
        "slot": slot
    }
    
    result = handle_message(state)
    print("Assistant:", result["response"])