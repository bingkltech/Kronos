"""
src/quant/quota_notifier.py — Autonomous Quota Enforcement & Email Alert Dispatcher.

Invariants:
1. Session Quota Auto-Pause: Triggers immediately when session trades reach the cap (default 50).
2. Email Dispatch: Sends an audit-grade HTML & plain-text alert to ALERT_EMAIL_TO upon reaching quota.
3. Fail-Safe Logging: Persists all notification records to data/email_notifications.json.
4. Concurrency Compliance: 3 Total Max = 2 Macro + 1 Scalp.
"""

import os
import sys
import json
import smtplib
import logging
import datetime
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal

logger = logging.getLogger("Kronos.QuotaNotifier")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s UTC] [%(levelname)s] [QuotaNotifier] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QUOTA_STATE_PATH = os.path.join(WORKSPACE_ROOT, "data", "aws_trade_quota.json")
NOTIFICATION_LOG_PATH = os.path.join(WORKSPACE_ROOT, "data", "email_notifications.json")


class QuotaNotifier:
    """Thread-safe trade quota monitor with automated SMTP email dispatch."""

    def __init__(self, quota_path: str = QUOTA_STATE_PATH):
        self.quota_path = quota_path
        self.lock = threading.Lock()
        self.trade_cap: Optional[int] = 50
        self.session_trades: int = 0
        self.macro_trades: int = 0
        self.scalp_trades: int = 0
        self.cap_reached_utc: Optional[datetime.datetime] = None
        self.is_active: bool = True
        self.last_email_sent_utc: Optional[datetime.datetime] = None
        self._load_state()

    def _load_state(self) -> None:
        """Loads persistent quota state from disk."""
        if not os.path.exists(self.quota_path):
            return
        try:
            with open(self.quota_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.trade_cap = int(d["live_trade_cap"]) if d.get("live_trade_cap") is not None else 50
            self.session_trades = max(0, int(d.get("live_session_trades", 0)))
            self.macro_trades = max(0, int(d.get("macro_trades", 0)))
            self.scalp_trades = max(0, int(d.get("scalp_trades", 0)))
            if d.get("live_cap_reached_utc"):
                self.cap_reached_utc = datetime.datetime.fromisoformat(d["live_cap_reached_utc"])
            if d.get("live_trading_enabled") is not None:
                self.is_active = bool(d["live_trading_enabled"])
            if self.trade_cap is not None and self.session_trades >= self.trade_cap:
                self.is_active = False
        except Exception as e:
            logger.warning("Could not load quota state: %s", e)

    def save_state(self) -> None:
        """Persists quota state to disk."""
        try:
            os.makedirs(os.path.dirname(self.quota_path), exist_ok=True)
            payload = {
                "live_trading_enabled": self.is_active,
                "live_trade_cap": self.trade_cap,
                "live_session_trades": self.session_trades,
                "macro_trades": self.macro_trades,
                "scalp_trades": self.scalp_trades,
                "live_cap_reached_utc": self.cap_reached_utc.isoformat() if self.cap_reached_utc else None,
                "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            tmp = self.quota_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self.quota_path)
        except Exception as e:
            logger.debug("Could not save quota state: %s", e)

    @property
    def has_quota_remaining(self) -> bool:
        """Checks if session trades are under the designated cap."""
        with self.lock:
            self._load_state()
            if self.trade_cap is None:
                return True
            return self.session_trades < self.trade_cap

    @property
    def trades_remaining(self) -> Optional[int]:
        """Returns the number of trades remaining before hitting the auto-pause cap."""
        with self.lock:
            self._load_state()
            if self.trade_cap is None:
                return None
            return max(0, self.trade_cap - self.session_trades)

    def reset_quota(self, new_cap: Optional[int] = 50) -> None:
        """Resets the session trade counter and re-activates trading."""
        with self.lock:
            self.session_trades = 0
            self.macro_trades = 0
            self.scalp_trades = 0
            self.trade_cap = new_cap
            self.is_active = True
            self.cap_reached_utc = None
            self.save_state()

    def record_dispatch(
        self,
        symbol: str,
        source: str,
        account_summary: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, bool]:
        """
        Records a trade dispatch.
        Returns (is_active, quota_just_reached).
        """
        with self.lock:
            self.session_trades += 1
            if source.upper() == "MACRO":
                self.macro_trades += 1
            else:
                self.scalp_trades += 1

            cap_str = f"{self.session_trades}/{self.trade_cap}" if self.trade_cap else f"{self.session_trades}/unlimited"
            logger.info("[LIVE TRADE QUOTA] Dispatched %s (%s) -> Count: %s", symbol, source, cap_str)

            quota_just_reached = False
            if self.trade_cap is not None and self.session_trades >= self.trade_cap:
                self.is_active = False
                self.cap_reached_utc = datetime.datetime.now(datetime.timezone.utc)
                quota_just_reached = True
                logger.warning(
                    "[AUTO-PAUSE CAP REACHED] %d/%d live trades executed! Auto-pausing trading & sending alert...",
                    self.session_trades,
                    self.trade_cap
                )

            self.save_state()

        if quota_just_reached:
            self.dispatch_completion_email(account_summary=account_summary)

        return self.is_active, quota_just_reached

    def dispatch_completion_email(
        self,
        account_summary: Optional[Dict[str, Any]] = None,
        recipient_override: Optional[str] = None
    ) -> bool:
        """
        Sends audit email to ALERT_EMAIL_TO when 50-trade quota is achieved.
        """
        to_email = recipient_override or os.getenv("ALERT_EMAIL_TO", "").strip()
        smtp_host = os.getenv("SMTP_HOST", "").strip()
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "").strip()
        smtp_pass = os.getenv("SMTP_PASS", "").strip()
        use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

        wallet = "N/A"
        avail = "N/A"
        if account_summary:
            wallet = f"${float(account_summary.get('total_wallet_balance_usd', 0)):,.2f} USDT"
            avail = f"${float(account_summary.get('available_balance_usd', 0)):,.2f} USDT"

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        inst_tag = os.getenv("KRONOS_INSTANCE_TAG", "PC")

        subject = f"[Kronos Alert] {self.session_trades}/{self.trade_cap} Trades Completed — Auto-Pause Triggered"
        text_body = f"""Kronos Quantitative Trading Engine — Quota Milestone Reached

Status          : AUTO-PAUSE STANDBY (Active Trading Paused)
Instance        : {inst_tag}
Completed Time  : {now_str}
Total Trades    : {self.session_trades} / {self.trade_cap}
Macro Trades    : {self.macro_trades}
Scalp Trades    : {self.scalp_trades}
Wallet Balance  : {wallet}
Available Collateral: {avail}
Max Concurrency : 3 Total (2 Macro + 1 Lightning Scalp)

All trading has been safely paused per your session instructions.
To resume or set a new quota, visit http://localhost:7070 or update KRONOS_LIVE_TRADE_CAP.
"""

        html_body = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0d1117; color: #c9d1d9; padding: 24px;">
            <div style="max-width: 600px; margin: 0 auto; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 24px;">
                <h2 style="color: #58a6ff; margin-top: 0; border-bottom: 1px solid #30363d; padding-bottom: 12px;">
                    🛡️ Kronos 50-Trade Milestone Achieved
                </h2>
                <div style="background: rgba(56, 139, 253, 0.1); border-left: 4px solid #58a6ff; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
                    <strong style="color: #58a6ff; font-size: 14px;">AUTO-PAUSE ACTIVATED:</strong>
                    <div style="color: #8b949e; font-size: 13px; margin-top: 4px;">
                        The session quota of <strong>{self.session_trades}/{self.trade_cap} trades</strong> has been reached. Trading has safely switched to <code>STANDBY_PAUSED</code>.
                    </div>
                </div>

                <table style="width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px;">
                    <tr style="border-bottom: 1px solid #21262d;">
                        <td style="padding: 8px 0; color: #8b949e;">Instance Tag</td>
                        <td style="padding: 8px 0; color: #f0f6fc; font-weight: 600; text-align: right;">{inst_tag}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #21262d;">
                        <td style="padding: 8px 0; color: #8b949e;">Completed UTC</td>
                        <td style="padding: 8px 0; color: #f0f6fc; font-weight: 600; text-align: right;">{now_str}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #21262d;">
                        <td style="padding: 8px 0; color: #8b949e;">Macro Dispatches</td>
                        <td style="padding: 8px 0; color: #58a6ff; font-weight: 600; text-align: right;">{self.macro_trades} trades</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #21262d;">
                        <td style="padding: 8px 0; color: #8b949e;">Scalp Dispatches</td>
                        <td style="padding: 8px 0; color: #f0883e; font-weight: 600; text-align: right;">{self.scalp_trades} trades</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #21262d;">
                        <td style="padding: 8px 0; color: #8b949e;">Wallet Balance</td>
                        <td style="padding: 8px 0; color: #00E676; font-weight: 700; text-align: right;">{wallet}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #8b949e;">Available Margin</td>
                        <td style="padding: 8px 0; color: #00E676; font-weight: 700; text-align: right;">{avail}</td>
                    </tr>
                </table>

                <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #30363d; font-size: 11px; color: #8b949e; text-align: center;">
                    Allocation: Max 3 Concurrent (2 Macro + 1 Scalp) &bull; Kronos Autonomous Cloud Engine
                </div>
            </div>
        </body>
        </html>
        """

        notification_record = {
            "timestamp_utc": now_str,
            "session_trades": self.session_trades,
            "trade_cap": self.trade_cap,
            "recipient": to_email,
            "status": "QUEUED"
        }

        # If SMTP is configured and recipient exists, dispatch live email
        if to_email and smtp_host and smtp_user and smtp_pass:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = smtp_user
                msg["To"] = to_email
                msg.attach(MIMEText(text_body, "plain"))
                msg.attach(MIMEText(html_body, "html"))

                if use_tls:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                        server.starttls()
                        server.login(smtp_user, smtp_pass)
                        server.sendmail(smtp_user, [to_email], msg.as_string())
                else:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                        server.login(smtp_user, smtp_pass)
                        server.sendmail(smtp_user, [to_email], msg.as_string())

                logger.info("[EMAIL DISPATCHED] 50-Trade completion notification successfully sent to %s", to_email)
                notification_record["status"] = "SENT"
                self.last_email_sent_utc = datetime.datetime.now(datetime.timezone.utc)
            except Exception as e:
                logger.error("[EMAIL ERROR] Failed delivering completion email to %s: %s", to_email, e)
                notification_record["status"] = f"FAILED: {e}"
        else:
            logger.info(
                "[EMAIL NOTIFIER] Quota reached. Record saved to %s (Set ALERT_EMAIL_TO, SMTP_HOST, SMTP_USER, SMTP_PASS in .env to receive live SMTP emails).",
                NOTIFICATION_LOG_PATH
            )
            notification_record["status"] = "RECORDED_NO_SMTP_CREDENTIALS"

        # Persist audit entry
        try:
            records = []
            if os.path.exists(NOTIFICATION_LOG_PATH):
                with open(NOTIFICATION_LOG_PATH, "r", encoding="utf-8") as f:
                    records = json.load(f)
            records.append(notification_record)
            with open(NOTIFICATION_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(records[-50:], f, indent=2)
        except Exception as e:
            logger.debug("Failed saving notification audit: %s", e)

        return notification_record.get("status") == "SENT"


# Module-level singleton for global quota enforcement across WebUI and workers
quota_mgr = QuotaNotifier()

