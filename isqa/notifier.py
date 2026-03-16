import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader

from isqa.constants import EMAIL_TEMPLATES_DIR
from isqa.logger import get_logger

logger = get_logger()


jinja_env = Environment(loader=FileSystemLoader(EMAIL_TEMPLATES_DIR))


class EmailConfig:
    """
    A class to hold and validate all email related data loaded from
    virtual environment variables.
    """

    def __init__(self):

        self.sender_email: Optional[str] = os.getenv("EMAIL_SENDER")
        self.sender_login: Optional[str] = os.getenv("EMAIL_LOGIN")
        self.sender_password: Optional[str] = os.getenv("EMAIL_PASSWORD")
        self.smtp_server: Optional[str] = os.getenv("SMTP_SERVER")
        self.recipient_bcc: Optional[str] = os.getenv("EMAIL_ADMIN_TO_NOTIFY_BCC", None)

        # Ensure default port 587 (TLS) or 465 (SSL) is used
        try:
            self.smtp_port: int = int(os.getenv("SMTP_PORT", 587))
        except ValueError:
            self.smtp_port: int = 587  # Default fallback
            logger.warning("Invalid SMTP_PORT value, defaulting to 587.")

        self.is_valid: bool = self._validate_config()

    def _validate_config(self) -> bool:
        """Checks if required configuration values are present."""
        if not all([self.sender_email, self.smtp_server]):
            logger.error(
                "Configuration ERROR: Missing one or more required environment variables (EMAIL_SENDER, SMTP_SERVER)."
            )
            return False
        logger.debug(
            "Email configuration loaded successfully from environment variables."
        )
        return True


def _render_single_template(template_name: str, context: Dict[str, Any]) -> str:
    """
    Renders a template using Jinja2 and the provided context data.

    Args:
        template_name: The name of the template file (e.g., 'welcome.html').
        context: A dictionary of variables to pass to the template.

    Returns:
        The rendered HTML content as a string.
    """
    try:
        template = jinja_env.get_template(template_name)
        return template.render(context)
    except Exception as e:
        logger.error(f"Error rendering Jinja2 template '{template_name}': {e}")
        return ""


def _send_html_email(
    recipient_email: str,
    subject: str,
    text_content: str,
    html_content: str,
    config: EmailConfig,
):
    """
    Sends an HTML email using SMTP with authentication.

    Args:
        recipient_email: The email address of the recipient.
        subject: The subject line of the email.
        text_content: The plain text fallback content.
        html_content: The HTML content for the email body.
        config: The EmailConfig object containing SMTP settings and credentials.
    """

    if not config.is_valid:
        logger.error("Cannot send email. Configuration is invalid.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.sender_email
    msg["To"] = recipient_email

    # Attach parts: plain text first for compatibility
    part1 = MIMEText(text_content, "plain")
    part2 = MIMEText(html_content, "html")

    msg.attach(part1)
    msg.attach(part2)

    server = None
    all_recipients = [recipient_email]
    if config.recipient_bcc is not None:
        all_recipients.append(config.recipient_bcc)

    try:
        logger.debug(
            f"Attempting to connect to SMTP server: {config.smtp_server}:{config.smtp_port}..."
        )

        if config.smtp_port == 465:
            server = smtplib.SMTP_SSL(config.smtp_server, config.smtp_port)
        else:
            server = smtplib.SMTP(config.smtp_server, config.smtp_port)
            server.starttls()  # Secure the connection

        if config.sender_login is not None:
            server.login(config.sender_login, config.sender_password)

        server.sendmail(config.sender_email, all_recipients, msg.as_string())
        server.quit()

        logger.debug(f"HTML email sent successfully to: {recipient_email}!")

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "SMTP Authentication Failed. Check your credentials (e.g., App Password for Gmail) and permissions."
        )
    except Exception as e:
        logger.error(
            f"An unexpected error occurred during email sending to {recipient_email}: {e}"
        )
    finally:
        if server:
            try:
                server.close()
            except Exception:
                pass


def _configure_and_send_email(
    user_email: str, subject: str, html_body: str, text_body: str
):
    email_config = EmailConfig()

    if not email_config.is_valid:
        logger.error("Cannot send email. Configuration is invalid.")
        return

    _send_html_email(
        recipient_email=user_email,
        subject=subject,
        text_content=text_body,
        html_content=html_body,
        config=email_config,
    )


def _render_templates(
    template_context: dict, template_file_html: str, template_file_txt: str
):
    html_body = _render_single_template(template_file_html, template_context)
    if not html_body:
        logger.error(
            f"Failed to generate HTML email body. Template: {template_file_html}"
        )
        return

    text_body = _render_single_template(template_file_txt, template_context)
    if not html_body:
        logger.error(
            f"Failed to generate text email body. Template: {template_file_txt}"
        )
        return

    return html_body, text_body


def send_email_on_problem(
    user_email: str, user_name: str, repository_name: str, issues_block: str
):

    template_context = {
        "user_name": user_name,
        "repository_name": repository_name,
        "issues_block": issues_block,
        "team_name": os.getenv("EMAIL_TEMPLATES_TEAM_NAME"),
    }

    subject = f"Problems with Gitlab Issues: {repository_name}"
    html_body, text_body = _render_templates(
        template_context, "problem.html", "problem.txt"
    )
    _configure_and_send_email(user_email, subject, html_body, text_body)


def send_email_due_date_expired(
    user_email: str, user_name: str, repository_name: str, issues_block: str
):

    template_context = {
        "user_name": user_name,
        "repository_name": repository_name,
        "issues_block": issues_block,
        "team_name": os.getenv("EMAIL_TEMPLATES_TEAM_NAME"),
    }

    subject = f"Gitlab Issues due date expired for the repository: {repository_name}"
    html_body, text_body = _render_templates(
        template_context, "due-date-expired.html", "due-date-expired.txt"
    )
    _configure_and_send_email(user_email, subject, html_body, text_body)


def send_email_missing_assignee(
    user_email: str, user_name: str, repository_name: str, issues_block: str
):

    template_context = {
        "user_name": user_name,
        "repository_name": repository_name,
        "issues_block": issues_block,
        "team_name": os.getenv("EMAIL_TEMPLATES_TEAM_NAME"),
    }

    subject = f"Gitlab Issues missing assignee in the repository: {repository_name}"
    html_body, text_body = _render_templates(
        template_context, "missing-assignee.html", "missing-assignee.txt"
    )
    _configure_and_send_email(user_email, subject, html_body, text_body)


def send_email_missing_label(
    user_email: str, user_name: str, repository_name: str, issues_block: str
):

    template_context = {
        "user_name": user_name,
        "repository_name": repository_name,
        "issues_block": issues_block,
        "team_name": os.getenv("EMAIL_TEMPLATES_TEAM_NAME"),
    }

    subject = f"Gitlab Issues missing label in the repository: {repository_name}"
    html_body, text_body = _render_templates(
        template_context, "missing-label.html", "missing-label.txt"
    )
    _configure_and_send_email(user_email, subject, html_body, text_body)
