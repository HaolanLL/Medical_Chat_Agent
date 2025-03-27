import os
from dotenv import load_dotenv
from twilio.rest import Client
import smtplib
from email.message import EmailMessage
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Optional, Dict, Any
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

class Notifier:
    def __init__(self):
        """Initialize with retry configuration"""
        self.max_retries = 3
        self.twilio_client = Client(
            os.getenv("TWILIO_SID"),
            os.getenv("TWILIO_TOKEN")
        )
        self.smtp_server = os.getenv("SMTP_SERVER")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.twilio_number = os.getenv("TWILIO_NUMBER")

    def validate_contact_info(self, to: str, channel: str) -> bool:
        """Validate phone/email format"""
        if channel == "sms":
            return re.match(r'^\+?[1-9]\d{1,14}$', to) is not None
        return re.match(r'^[^@]+@[^@]+\.[^@]+$', to) is not None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def send_notification(self, doctor_id: str, message: str) -> Dict[str, Any]:
        """Send notification with fallback logic"""
        if not message or len(message) > 500:
            raise ValueError("Invalid message length")

        channel = os.getenv("PREFERRED_CHANNEL", "sms")
        contact_info = os.getenv("DOCTOR_PHONE" if channel == "sms" else "DOCTOR_EMAIL")
        
        if not self.validate_contact_info(contact_info, channel):
            logger.error(f"Invalid contact info for {channel}")
            return {"status": "error", "message": "Invalid contact information"}

        try:
            if channel == "sms":
                return self._send_sms_with_fallback(contact_info, message)
            return self._send_email_with_fallback(contact_info, message)
        except Exception as e:
            logger.error(f"All notification attempts failed: {e}")
            return {"status": "error", "message": "Notification delivery failed"}

    def _send_sms_with_fallback(self, to: str, body: str) -> Dict[str, Any]:
        """Try SMS first, fallback to email"""
        try:
            return self._send_sms(to, body)
        except Exception as sms_error:
            logger.warning(f"SMS failed, trying email: {sms_error}")
            email = os.getenv("DOCTOR_EMAIL")
            if email and self.validate_contact_info(email, "email"):
                return self._send_email(email, "Appointment Notification", body)
            raise

    def _send_email_with_fallback(self, to: str, subject: str, content: str) -> Dict[str, Any]:
        """Try email first, fallback to SMS"""
        try:
            return self._send_email(to, subject, content)
        except Exception as email_error:
            logger.warning(f"Email failed, trying SMS: {email_error}")
            phone = os.getenv("DOCTOR_PHONE")
            if phone and self.validate_contact_info(phone, "sms"):
                return self._send_sms(phone, f"{subject}: {content[:100]}...")
            raise

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
    def _send_sms(self, to: str, body: str) -> Dict[str, Any]:
        """Send SMS with retry logic"""
        message = self.twilio_client.messages.create(
            body=body,
            from_=self.twilio_number,
            to=to
        )
        logger.info(f"SMS sent to {to}, SID: {message.sid}")
        return {"status": "success", "message_id": message.sid}

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
    def _send_email(self, to: str, subject: str, content: str) -> Dict[str, Any]:
        """Send email with retry logic"""
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = to
        msg.set_content(content)

        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
        
        logger.info(f"Email sent to {to}, Subject: {subject}")
        return {"status": "success", "message": "Email delivered"}

# Example usage
if __name__ == "__main__":
    notifier = Notifier()
    result = notifier.send_notification(
        doctor_id="DR-456",
        message="New appointment booked for PAT-123"
    )
    print("Notification result:", result)