import json
import os
import requests
from typing import Dict, Any, List

DATA_URL = "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/refs/heads/main/data/bugcrowd_data.json"
STATE_FILE = "bugcrowd_state.json"

# --- تنظیمات تلگرام ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8103031360:AAEIxnPSqEhfLRKYuz1OUqjMrSXNMYnL6rU")

# آیدی کانال تلگرام
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003572107779")

# در صورتی که دیسکورد هم مدنظرتان باشد:
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# برنامه‌هایی که قصد رصد آن‌ها را دارید (بخشی از نام یا URL را بنویسید).
# اگر خالی باشد []، تمامی تارگت‌ها و برنامه‌های باگ‌کرود رصد می‌شوند!
WATCHED_PROGRAMS = [
    # "coindesk",
    # "CCData-mbb-og"
]

def send_alert(message: str):
    """ارسال پیام به کنسول و تلگرام"""
    print(f"\n[ALERT]\n{message}\n")

    # ارسال به تلگرام
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID != "YOUR_CHAT_ID_HERE":
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            }
            res = requests.post(url, json=payload, timeout=15)
            if not res.ok:
                print(f"[-] Telegram API error: {res.text}")
        except Exception as e:
            print(f"[-] Telegram notification failed: {e}")

    # ارسال به Discord (اختیاری)
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        except Exception as e:
            print(f"[-] Discord notification failed: {e}")

def fetch_data() -> List[Dict[str, Any]]:
    """دریافت آخرین نسخه فایل داده از گیتهاب"""
    res = requests.get(DATA_URL, timeout=30)
    res.raise_for_status()
    return res.json()

def normalize_program_data(programs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """تبدیل داده‌های خام به ساختار مقایسه‌پذیر"""
    normalized = {}
    for prog in programs:
        url = prog.get("url", "").strip()
        name = prog.get("name", "").strip()
        if not url:
            continue

        if WATCHED_PROGRAMS:
            matched = any(
                keyword.lower() in name.lower() or keyword.lower() in url.lower()
                for keyword in WATCHED_PROGRAMS
            )
            if not matched:
                continue

        in_scope = set()
        for t in prog.get("targets", {}).get("in_scope", []):
            target_val = t.get("target") or t.get("uri") or t.get("name")
            if target_val:
                in_scope.add(f"[{t.get('type', 'asset')}] {target_val}")

        out_of_scope = set()
        for t in prog.get("targets", {}).get("out_of_scope", []):
            target_val = t.get("target") or t.get("uri") or t.get("name")
            if target_val:
                out_of_scope.add(f"[{t.get('type', 'asset')}] {target_val}")

        normalized[url] = {
            "name": name,
            "url": url,
            "max_payout": prog.get("max_payout", 0),
            "in_scope": sorted(list(in_scope)),
            "out_of_scope": sorted(list(out_of_scope))
        }
    return normalized

def diff_states(old_state: Dict[str, Any], new_state: Dict[str, Any]):
    """مقایسه داده‌های جدید با آخرین وضعیت ذخیره شده"""
    alerts = []

    # ۱. برنامه‌های جدید
    new_programs = set(new_state.keys()) - set(old_state.keys())
    for prog_url in new_programs:
        prog = new_state[prog_url]
        alerts.append(
            f"🆕 New Program Detected!\n"
            f"• Name: {prog['name']}\n"
            f"• URL: {prog['url']}\n"
            f"• Max Payout: ${prog['max_payout']}\n"
            f"• In-Scope Targets: {len(prog['in_scope'])}"
        )

    # ۲. بررسی تغییرات در برنامه‌های موجود
    common_programs = set(new_state.keys()) & set(old_state.keys())
    for prog_url in common_programs:
        old_p = old_state[prog_url]
        new_p = new_state[prog_url]

        old_in = set(old_p.get("in_scope", []))
        new_in = set(new_p.get("in_scope", []))

        added_in_scope = new_in - old_in
        removed_in_scope = old_in - new_in

        # تارگت جدید به In-Scope اضافه شده
        if added_in_scope:
            items_str = "\n".join([f"  + {item}" for item in added_in_scope])
            alerts.append(
                f"🎯 New In-Scope Targets Added!\n"
                f"• Program: {new_p['name']} ({new_p['url']})\n"
                f"• Added:\n{items_str}"
            )

        # تارگت از In-Scope حذف شده
        if removed_in_scope:
            items_str = "\n".join([f"  - {item}" for item in removed_in_scope])
            alerts.append(
                f"⚠️ Targets Removed from In-Scope!\n"
                f"• Program: {new_p['name']} ({new_p['url']})\n"
                f"• Removed:\n{items_str}"
            )

        # تغییرات در سقف پاداش
        if old_p.get("max_payout") != new_p.get("max_payout"):
            alerts.append(
                f"💰 Payout Changed!\n"
                f"• Program: {new_p['name']}\n"
                f"• From: ${old_p.get('max_payout')} ➔ To: ${new_p.get('max_payout')}"
            )

    return alerts

def run_watchtower():
    print("[*] Fetching latest Bugcrowd data...")
    raw_data = fetch_data()
    current_state = normalize_program_data(raw_data)

    if not os.path.exists(STATE_FILE):
        print(f"[*] First run: Saving baseline state ({len(current_state)} programs)...")
        with open(STATE_FILE, "w") as f:
            json.dump(current_state, f, indent=2)
        print("[+] Baseline created. Future runs will detect changes.")
        send_alert("✅ Bugcrowd Watchtower is active! Baseline created.")
        return

    with open(STATE_FILE, "r") as f:
        old_state = json.load(f)

    alerts = diff_states(old_state, current_state)

    if alerts:
        print(f"[!] Found {len(alerts)} change(s)!")
        for alert in alerts:
            send_alert(alert)
        with open(STATE_FILE, "w") as f:
            json.dump(current_state, f, indent=2)
    else:
        print("[*] No changes detected.")

if __name__ == "__main__":
    run_watchtower()
