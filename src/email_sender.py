import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(subject: str, body_text: str) -> None:
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("DIGEST_RECIPIENT", sender)

    if not sender or not password:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD are not set in the environment")

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)


if __name__ == "__main__":
    from datetime import date

    from dotenv import load_dotenv

    load_dotenv()
    send_email(
        subject=f"Test digest - {date.today().isoformat()}",
        body_text="This is a test of the daily financial digest email sender.",
    )
    print("Test email sent.")
