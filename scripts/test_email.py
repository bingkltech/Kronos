"""
scripts/test_email.py — Test Kronos SMTP Email Notifications.

Usage:
    python scripts/test_email.py [recipient@example.com]
"""

import os
import sys
import dotenv

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)
dotenv.load_dotenv(os.path.join(WORKSPACE_ROOT, ".env"))

from src.quant.quota_notifier import QuotaNotifier

def main():
    recipient = sys.argv[1] if len(sys.argv) > 1 else os.getenv("ALERT_EMAIL_TO", "").strip()
    if not recipient:
        print("[!] No recipient email specified.")
        print("    Usage: python scripts/test_email.py your_email@example.com")
        print("    Or set ALERT_EMAIL_TO in .env")
        return

    print("============================================================================")
    print(" [Kronos] Testing Email Notification Dispatch")
    print(f" Recipient : {recipient}")
    print(f" SMTP Host : {os.getenv('SMTP_HOST', '(not set)')}")
    print(f" SMTP Port : {os.getenv('SMTP_PORT', '587')}")
    print(f" SMTP User : {os.getenv('SMTP_USER', '(not set)')}")
    print("============================================================================")

    notifier = QuotaNotifier()
    success = notifier.dispatch_completion_email(
        account_summary={
            "total_wallet_balance_usd": "194.01",
            "available_balance_usd": "179.03"
        },
        recipient_override=recipient
    )

    if success:
        print(">> [SUCCESS] Email dispatched successfully to " + recipient)
    else:
        print(">> [NOTICE] Email could not be sent live over SMTP (credentials missing or connection rejected).")
        print("   The notification record was safely logged to data/email_notifications.json.")
        print("   To enable live delivery, ensure ALERT_EMAIL_TO, SMTP_HOST, SMTP_USER, SMTP_PASS are set in .env.")

if __name__ == "__main__":
    main()
