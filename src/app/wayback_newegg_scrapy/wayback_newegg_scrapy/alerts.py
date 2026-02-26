"""
alerts.py
=========
Add this to your wayback_newegg_scrapy project.
Sends a Windows desktop notification + email when a price drops
below your defined thresholds.

Usage:
  1. Set your PRICE_ALERTS and email config below
  2. Add AlertPipeline to ITEM_PIPELINES in settings.py (see bottom of file)
"""

import sqlite3
import smtplib
import subprocess
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ============================================================
# CONFIGURE YOUR PRICE ALERTS HERE
# Set a target price for each product — you get notified
# when the scraped price drops AT or BELOW that threshold
# ============================================================
PRICE_ALERTS = {
    "ASUS TUF RTX 4070":   550.00,   # alert if price <= $550
    "Intel Core i9-13900K": 350.00,  # alert if price <= $350
    # Add more:
    # "Your Product Name": 199.99,
}

# ============================================================
# EMAIL CONFIG (optional — leave empty to skip email alerts)
# Uses Gmail by default — for other providers change SMTP settings
# For Gmail: use an App Password, not your real password
# https://myaccount.google.com/apppasswords
# ============================================================
EMAIL_CONFIG = {
    "enabled":       False,          # set to True to enable emails
    "sender":        "you@gmail.com",
    "password":      "your_app_password_here",
    "recipient":     "you@gmail.com",
    "smtp_server":   "smtp.gmail.com",
    "smtp_port":     587,
}


class AlertPipeline:
    """
    Runs after SQLitePipeline and CSVPipeline.
    For each scraped price, checks if it's at or below the threshold
    and fires a Windows notification + optional email.
    """

    def open_spider(self, spider):
        # Track what we've already alerted on this session
        # so you don't get 50 notifications for the same product
        self.alerted_this_session = set()

    def process_item(self, item, spider):
        name  = item["product_name"]
        price = item["price"]
        date  = item["snapshot_date"]
        url   = item["archive_url"]

        if name not in PRICE_ALERTS:
            return item

        threshold = PRICE_ALERTS[name]

        if price <= threshold:
            alert_key = f"{name}_{date}"

            # Only alert once per product per session
            if alert_key not in self.alerted_this_session:
                self.alerted_this_session.add(alert_key)
                self._fire_alert(name, price, threshold, date, url)

        return item

    def _fire_alert(self, name, price, threshold, date, url):
        message = (
            f"{name}\n"
            f"Price: ${price:.2f}  (your target: ${threshold:.2f})\n"
            f"Date: {date}"
        )
        print(f"\n  🔔 PRICE ALERT! {message}\n")

        self._windows_notification(name, price, threshold)

        if EMAIL_CONFIG["enabled"]:
            self._send_email(name, price, threshold, date, url)

    def _windows_notification(self, name, price, threshold):
        """
        Fire a Windows 10/11 toast notification using PowerShell.
        No extra libraries needed — uses built-in Windows APIs.
        """
        title   = "💰 Newegg Price Alert!"
        message = f"{name} dropped to ${price:.2f} (target: ${threshold:.2f})"

        # Escape single quotes for PowerShell
        title_ps   = title.replace("'", "''")
        message_ps = message.replace("'", "''")

        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title_ps}</text>
      <text>{message_ps}</text>
    </binding>
  </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Newegg Price Tracker').Show($toast)
"""
        try:
            subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                timeout=10,
            )
        except Exception as e:
            print(f"  ⚠ Notification failed: {e}")

    def _send_email(self, name, price, threshold, date, archive_url):
        """Send an email alert via Gmail (or other SMTP provider)."""
        cfg = EMAIL_CONFIG

        subject = f"💰 Price Alert: {name} dropped to ${price:.2f}"
        body = f"""
<h2>Newegg Price Alert</h2>
<table>
  <tr><td><b>Product</b></td><td>{name}</td></tr>
  <tr><td><b>Price</b></td><td>${price:.2f}</td></tr>
  <tr><td><b>Your Target</b></td><td>${threshold:.2f}</td></tr>
  <tr><td><b>Snapshot Date</b></td><td>{date}</td></tr>
  <tr><td><b>Archive Link</b></td><td><a href="{archive_url}">{archive_url}</a></td></tr>
</table>
"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["sender"]
        msg["To"]      = cfg["recipient"]
        msg.attach(MIMEText(body, "html"))

        try:
            with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["sender"], cfg["password"])
                server.sendmail(cfg["sender"], cfg["recipient"], msg.as_string())
            print(f"  ✓ Email alert sent to {cfg['recipient']}")
        except Exception as e:
            print(f"  ⚠ Email failed: {e}")
