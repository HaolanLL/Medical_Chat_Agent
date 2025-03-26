from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.chat_models import FakeListChatModel
from langchain_core.runnables import RunnablePassthrough
from typing import TypedDict, List, Annotated
import operator

# Import our validated RAG setup
from rag_setup import setup_knowledge_base

class AgentState(TypedDict):
    messages: Annotated[List[dict], operator.add]
    patient_id: str = None
    appointment_type: str = None

# Initialize components with test configuration
clinic_retriever = setup_knowledge_base()
test_responses = [
    "How can I help with your appointment today?",
    "Please provide your patient ID",
    "What type of appointment do you need?",
    "Appointment booked for tomorrow at 2 PM"
]
model = FakeListChatModel(responses=test_responses)

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a medical clinic assistant. Help patients with:
     - Appointment scheduling
     - Prescription refills
     - General clinic information
     - Insurance queries
     
     Use the clinic documentation when needed.
     Current patient: {patient_id}"""),
    ("placeholder", "{messages}")
])

def retrieve_docs(state: AgentState):
    """Retrieve relevant clinic documents based on conversation"""
    last_message = state['messages'][-1].content
    return {"context": clinic_retriever.invoke(last_message)}

def generate_response(state: AgentState):
    """Generate AI response with context"""
    response = prompt | model.bind(stop=["<|im_end|>"]) | StrOutputParser()
    return {"messages": [AIMessage(content=response.invoke({
        "messages": state['messages'],
        "context": state.get('context', ''),
        "patient_id": state.get('patient_id', 'new patient')
    }))]}

def handle_appointment(state: AgentState):
    """Process appointment booking logic with validation
    
    Args:
        state: Current conversation state containing appointment details
        
    Returns:
        Updated state with booking confirmation or error message
        
    Raises:
        ValueError: For invalid patient IDs or appointment types
    """
    # Validate patient ID format
    if not state.get('patient_id') or not state['patient_id'].startswith("PAT-"):
        return {"messages": [AIMessage(content="Invalid patient ID format. Must start with PAT-")]}
    
    # Validate appointment type
    valid_types = {"checkup", "consultation", "follow-up", "emergency"}
    if state.get('appointment_type') not in valid_types:
        return {"messages": [AIMessage(
            content=f"Invalid appointment type. Choose from: {', '.join(valid_types)}"
        )]}
    
    try:
        # Database update with error handling
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO appointments (patient_id, type, status)
                    VALUES (%s, %s, 'scheduled')
                    RETURNING id, scheduled_time
                """, (state['patient_id'], state['appointment_type']))
                result = cur.fetchone()
                conn.commit()
                
        return {"messages": [AIMessage(
            content=f"Appointment {result[0]} booked for {result[1]}"
        )]}
        
    except psycopg2.Error as e:
        return {"messages": [AIMessage(
            content=f"Booking failed: {str(e)}"
        )]}

# Build the workflow
workflow = StateGraph(AgentState)
workflow.add_node("retrieve", retrieve_docs)
workflow.add_node("generate", generate_response)
workflow.add_node("book_appointment", handle_appointment)

# Define edges
workflow.add_conditional_edges(
    "generate",
    lambda state: "book_appointment" if "book" in state['messages'][-1].content.lower() else END
)
workflow.add_edge("retrieve", "generate")
workflow.add_edge("book_appointment", END)

# Set entry point
workflow.set_entry_point("retrieve")
conversation = workflow.compile()

def execute_conversation():
    """Run interactive conversation"""
    state = {"messages": []}
    while True:
        user_input = input("Patient: ")
        state = conversation.invoke({
            **state,
            "messages": [HumanMessage(content=user_input)]
        })
        print("Assistant:", state['messages'][-1].content)

if __name__ == "__main__":
    execute_conversation()
from typing import TypedDict, Optional, List
from langgraph.graph import StateGraph, END
from langchain_core.tools import Tool
from langchain_core.messages import HumanMessage
import psycopg2
from dotenv import load_dotenv
import os
from datetime import datetime
import uuid

load_dotenv()

# State definition
class AgentState(TypedDict):
    messages: List[HumanMessage]
    patient_id: Optional[str]
    doctor_id: Optional[str]
    slot: Optional[datetime]
    status: Optional[str]
    metadata: Optional[dict]

# Database connection
def get_db_connection():
    """Get managed database connection with connection pooling and error handling"""
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            connect_timeout=5
        )
        conn.autocommit = False  # Explicit transaction control
        return conn
    except psycopg2.OperationalError as e:
        logger.error(f"Database connection failed: {str(e)}")
        raise
    except Exception as e:
        logger.critical(f"Unexpected connection error: {str(e)}")
        raise

# Tools
def check_availability(state: AgentState):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM appointments 
                WHERE doctor_id = %s AND slot = %s AND status != 'cancelled'
            """, (state['doctor_id'], state['slot']))
            available = cur.fetchone()[0] == 0
    return {"available": available}

def create_appointment(state: AgentState):
    appointment_id = uuid.uuid4()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO appointments 
                (id, patient_id, doctor_id, slot, status, metadata)
                VALUES (%s, %s, %s, %s, 'pending', %s)
            """, (appointment_id, state['patient_id'], 
                 state['doctor_id'], state['slot'], 
                 state['metadata']))
            conn.commit()
    return {"appointment_id": appointment_id}

# Build workflow
workflow = StateGraph(AgentState)

# Define nodes
workflow.add_node("collect_details", lambda state: state)
workflow.add_node("check_availability", check_availability)
workflow.add_node("confirm_booking", lambda state: state)
workflow.add_node("create_appointment", create_appointment)
workflow.add_node("notify_doctor", lambda state: state)

# Define edges
workflow.set_entry_point("collect_details")
workflow.add_edge("collect_details", "check_availability")
workflow.add_conditional_edges(
    "check_availability",
    lambda state: "available" if state["available"] else "unavailable",
    {"available": "confirm_booking", "unavailable": END}
)
workflow.add_edge("confirm_booking", "create_appointment")
workflow.add_edge("create_appointment", "notify_doctor")
workflow.add_edge("notify_doctor", END)

# Compile
agent = workflow.compile()