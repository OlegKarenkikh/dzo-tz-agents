import os
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# IMAP — Агент ДЗО
DZO_IMAP_HOST     = os.getenv("DZO_IMAP_HOST", os.getenv("IMAP_HOST", "imap.company.ru"))
DZO_IMAP_PORT     = int(os.getenv("DZO_IMAP_PORT", 993))
DZO_IMAP_USER     = os.getenv("DZO_IMAP_USER", os.getenv("IMAP_USER"))
DZO_IMAP_PASSWORD = os.getenv("DZO_IMAP_PASSWORD", os.getenv("IMAP_PASSWORD"))
DZO_IMAP_FOLDER   = os.getenv("DZO_IMAP_FOLDER", "INBOX")
DZO_SMTP_FROM     = os.getenv("DZO_SMTP_FROM", os.getenv("SENDER_EMAIL", "ucz@company.ru"))

# IMAP — Агент ТЗ
TZ_IMAP_HOST      = os.getenv("TZ_IMAP_HOST", os.getenv("IMAP_HOST", "imap.company.ru"))
TZ_IMAP_PORT      = int(os.getenv("TZ_IMAP_PORT", 993))
TZ_IMAP_USER      = os.getenv("TZ_IMAP_USER", os.getenv("IMAP_USER"))
TZ_IMAP_PASSWORD  = os.getenv("TZ_IMAP_PASSWORD", os.getenv("IMAP_PASSWORD"))
TZ_IMAP_FOLDER    = os.getenv("TZ_IMAP_FOLDER", "INBOX")
TZ_SMTP_FROM      = os.getenv("TZ_SMTP_FROM", os.getenv("SENDER_EMAIL", "ucz@company.ru"))

# SMTP
SMTP_HOST         = os.getenv("SMTP_HOST", "smtp.company.ru")
SMTP_PORT         = int(os.getenv("SMTP_PORT", 587))
SMTP_USER         = os.getenv("SMTP_USER")
SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD")
MANAGER_EMAIL     = os.getenv("MANAGER_EMAIL", "manager@company.ru")

# LLM
MODEL_NAME        = os.getenv("MODEL_NAME", "gpt-4o")
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", 300))
