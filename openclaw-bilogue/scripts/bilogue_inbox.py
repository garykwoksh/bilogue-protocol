#!/usr/bin/env python3
"""
bilogue_inbox.py — OpenClaw skill 用：讀取你嘅 Bilogue 未讀訊息（讀完即清）。

用法：
  python3 bilogue_inbox.py

需要環境變數：BILOGUE_RELAY_URL, BILOGUE_AGENT_ID, BILOGUE_READ_TOKEN
輸出：JSON — {"http": 200, "count": N, "messages": [...]}
"""
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    relay_url = os.environ.get("BILOGUE_RELAY_URL", "").rstrip("/")
    agent_id = os.environ.get("BILOGUE_AGENT_ID")
    read_token = os.environ.get("BILOGUE_READ_TOKEN")
    if not relay_url or not agent_id or not read_token:
        print(json.dumps({"error": "缺環境變數 BILOGUE_RELAY_URL / BILOGUE_AGENT_ID / BILOGUE_READ_TOKEN"}))
        sys.exit(2)

    req = urllib.request.Request(
        f"{relay_url}/inbox/{agent_id}",
        headers={"Authorization": f"Bearer {read_token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code, out = resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        code, out = e.code, json.loads(e.read())
    except Exception as e:
        print(json.dumps({"error": f"連唔到 relay：{type(e).__name__}: {e}"}))
        sys.exit(1)

    # 精簡輸出，等 agent 易睇
    msgs = [{
        "msg_id": m.get("msg_id"),
        "sender": m.get("sender"),
        "intent_type": m.get("intent_type"),
        "payload": m.get("payload"),
        "in_reply_to": m.get("in_reply_to"),
        "delivery": m.get("delivery"),
    } for m in out.get("messages", [])]
    print(json.dumps({"http": code, "count": len(msgs), "messages": msgs},
                     ensure_ascii=False))
    sys.exit(0 if code == 200 else 1)


if __name__ == "__main__":
    main()
