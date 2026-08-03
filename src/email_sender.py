import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(subject: str, html_body: str, text_body: str | None = None) -> None:
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("DIGEST_RECIPIENT", sender)

    if not sender or not password:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD are not set in the environment")

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    # Plain text first, HTML last - clients that support HTML render the last
    # part they understand, others fall back to the plain text part.
    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

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
        html_body="<p>This is a test of the daily financial digest email sender.</p>",
        text_body="This is a test of the daily financial digest email sender.",
    )
    print("Test email sent.")
