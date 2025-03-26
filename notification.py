import os
from dotenv import load_dotenv
from twilio.rest import Client
import smtplib
from email.message import EmailMessage

load_dotenv()

class Notifier:
    def __init__(self):
        self.twilio_client = Client(
            os.getenv("TWILIO_SID"),
            os.getenv("TWILIO_TOKEN")
        )
        self.smtp_server = os.getenv("SMTP_SERVER")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")

    def send_notification(self, doctor_id, message):
        """Send notification via doctor's preferred channel"""
        # In real implementation, get doctor preferences from DB
        channel = os.getenv("PREFERRED_CHANNEL", "sms")
        
        if channel == "sms":
            self._send_sms(
                to=os.getenv("DOCTOR_PHONE"),
                body=message
            )
        else:
            self._send_email(
                to=os.getenv("DOCTOR_EMAIL"),
                subject="New Appointment Notification",
                content=message
            )

    def _send_sms(self, to, body):
        self.twilio_client.messages.create(
            body=body,
            from_=os.getenv("TWILIO_NUMBER"),
            to=to
        )

    def _send_email(self, to, subject, content):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = to
        msg.set_content(content)

        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)