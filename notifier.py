"""
Notificador por Telegram para Radar Remates
"""

import requests
import os
import time

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(message: str):
    """Envía mensaje por Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM] No configurado. Mensaje:\n{message}\n")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[TELEGRAM] ✅ Enviado")
            time.sleep(1)  # Rate limit Telegram
            return True
        else:
            print(f"[TELEGRAM] ❌ Error {resp.status_code}: {resp.text}")
            # Si falla por Markdown, intentar sin formato
            payload["parse_mode"] = None
            resp2 = requests.post(url, json=payload, timeout=10)
            return resp2.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM] ❌ Error: {e}")
        return False
