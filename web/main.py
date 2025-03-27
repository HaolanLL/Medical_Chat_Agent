from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from appointment_agent import handle_message
from notification import Notifier
from typing import Dict, Any
import logging
from dotenv import load_dotenv
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(
    title="Medical Appointment Chatbot",
    version=os.getenv("APP_VERSION", "1.0.0"),
    docs_url="/docs",
    redoc_url=None
)

# Security middleware
if os.getenv("ENVIRONMENT") == "production":
    app.add_middleware(HTTPSRedirectMiddleware)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize services
notifier = Notifier()

@app.get("/", response_class=HTMLResponse)
async def chat_interface(request: Request):
    """Serve chat interface"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": app.version,
        "services": ["chat", "appointments", "notifications"]
    }

@app.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat"""
    await websocket.accept()
    logger.info("New WebSocket connection established")
    
    try:
        while True:
            try:
                user_input = await websocket.receive_text()
                if not user_input.strip():
                    raise HTTPException(status_code=400, detail="Empty message")
                
                # Process message
                state = {
                    "messages": [{"content": user_input}],
                    "patient_id": "demo-patient"  # In real app, get from auth
                }
                
                response = handle_message(state)
                await websocket.send_text(response["response"])
                
                # Notify staff if booking was made
                if "book" in response["response"].lower():
                    notifier.send_notification(
                        doctor_id="demo-doctor",
                        message=f"New appointment request: {user_input[:100]}"
                    )
                    
            except HTTPException as e:
                await websocket.send_text(f"Error: {e.detail}")
                logger.warning(f"Client error: {e.detail}")
            except Exception as e:
                logger.error(f"Chat error: {str(e)}")
                await websocket.send_text("Sorry, we encountered an error")
                raise
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await websocket.close(code=1011)  # Internal error
        raise

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Global HTTP exception handler"""
    logger.error(f"HTTP error {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        log_level="info"
    )