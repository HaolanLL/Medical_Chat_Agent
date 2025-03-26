# System Architecture

```mermaid
graph TD
    A[User Interface] --> B(Chatbot Core)
    B --> C[LangChain Integration]
    B --> D[Appointment Management]
    C --> E[RAG System]
    C --> F[LangGraph State]
    D --> G[Calendar Integration]
    D --> H[Notifications]