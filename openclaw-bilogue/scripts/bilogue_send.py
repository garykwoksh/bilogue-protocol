#!/usr/bin/env python3
"""
bilogue_send.py — OpenClaw skill 用：簽名並發送一個 Bilogue envelope。

用法：
  python3 bilogue_send.py --receiver stfund --intent DELEGATE \
      --payload '{"task": "Q3 覆核"}'
  python3 bilogue_send.py --receiver karina --intent PROPOSE \
      --payload '{"plan": "..."}' --in-reply-to msg-abc12345

需要環境變數：BILOGUE_RELAY_URL, BILOGUE_AGENT_ID, BILOGUE_SECRET
輸出：JSON — {"http": <status>, "msg_id": "...", "relay": {...}}
"""
import argparse
import hashlib
import hmac
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

INTENT_TYPES = {"QUERY", "DELEGATE", "PROPOSE", "ACCEPT", "REJECT", "REPORT", "PING"}

# P0-07: 共用 bilogue_crypto 做簽名；若 skill 單獨部署搵唔到，用內聯相同實作兜底
try:
    from bilogue_crypto import sign as _bc_sign
except ImportError:
    import hashlib as _hl
    import hmac as _hm

    def _bc_sign(envelope, secret):
        body = json.dumps({k: v for k, v in envelope.items() if k != "sig"},
                          sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
        return _hm.new(secret.encode(), body.encode(), _hl.sha256).hexdigest()


def _build_ssl_context(ca_cert):
    """P1-01 (client): 建立 TLS context。
    - ca_cert 提供：信任該 CA（支援 relay 自簽證書）
    - 否則：用系統預設（公網證書）；http:// 則返回 None
    """
    if not ca_cert:
        return None
    ctx = ssl.create_default_context(cafile=ca_cert)
    return ctx


def _safe_parse_error(e):
    """P1-04: error response 唔一定係 JSON —— 安全讀取，唔洩漏 token / 堆棧。"""
    try:
        raw = e.read(4096)
    except Exception:
        return {"error": "relay 回應讀取失敗"}
    try:
        return json.loads(raw)
    except Exception:
        return {"error": raw.decode("utf-8", "replace")[:200]}


def _post(relay_url, env, ca_cert, max_retries):
    """P1-04: 發送 envelope。
    - 連接層錯誤（URLError / timeout）→ 按 max_retries 退避重試
    - 應用層錯誤（HTTPError，例如 401/403/429）→ 唔重試，直接返回
    返回 (code, out)。"""
    url = f"{relay_url}/send"
    data = json.dumps(env).encode()
    ctx = _build_ssl_context(ca_cert)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            opener = urllib.request.build_opener()
            if ctx is not None:
                opener = urllib.request.build_opener(
                    urllib.request.HTTPSHandler(context=ctx))
            with opener.open(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # 應用層錯誤：唔重試（避免重放 / 雙重發送）
            return e.code, _safe_parse_error(e)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.2 * (attempt + 1))  # 簡單指數退避
                continue
            return None, {"error": f"連唔到 relay（{type(e).__name__}）：{e}"}
    return None, {"error": f"連唔到 relay：{last_err}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--receiver", required=True)
    ap.add_argument("--intent", required=True)
    ap.add_argument("--payload", required=True, help="JSON 字串")
    ap.add_argument("--in-reply-to", default=None)
    ap.add_argument("--ca-cert", default=os.environ.get("BILOGUE_CA_CERT"),
                    help="P1-01: relay TLS 自簽證書 CA（https 時用）")
    ap.add_argument("--max-retries", type=int, default=3,
                    help="P1-04: 連接層錯誤退避重試次數（默認 3）")
    args = ap.parse_args()

    relay_url = os.environ.get("BILOGUE_RELAY_URL", "").rstrip("/")
    agent_id = os.environ.get("BILOGUE_AGENT_ID")
    secret = os.environ.get("BILOGUE_SECRET")
    if not relay_url or not agent_id or not secret:
        print(json.dumps({"error": "缺環境變數 BILOGUE_RELAY_URL / BILOGUE_AGENT_ID / BILOGUE_SECRET"}))
        sys.exit(2)

    # P1-01: 安全提示 —— https 先係加密傳輸
    if relay_url.startswith("http://") and args.ca_cert is None:
        sys.stderr.write("  ⚠️  用緊 http://（明文）。生產環境請用 https:// + --ca-cert。\n")

    intent = args.intent.upper()
    if intent not in INTENT_TYPES:
        print(json.dumps({"error": f"intent 要係 {sorted(INTENT_TYPES)} 其中之一"}))
        sys.exit(2)

    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"payload 唔係合法 JSON：{e}"}))
        sys.exit(2)

    env = {
        "msg_id": f"msg-{uuid.uuid4().hex}",  # P0-06: full UUID
        "sender": agent_id,
        "receiver": args.receiver,
        "intent_type": intent,
        "payload": payload,
        "in_reply_to": args.in_reply_to,
        "nonce": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    env["sig"] = _bc_sign(env, secret)  # P0-07: 共用 bilogue_crypto

    code, out = _post(relay_url, env, args.ca_cert, args.max_retries)

    # P1-04: 清晰分類結果
    if code is None:
        print(json.dumps({"http": None, "msg_id": env["msg_id"], "relay": out},
                         ensure_ascii=False))
        sys.exit(1)  # 連接失敗
    print(json.dumps({"http": code, "msg_id": env["msg_id"], "relay": out},
                     ensure_ascii=False))
    sys.exit(0 if code in (200, 202) else 1)  # 200/202 = 成功送達或排隊


if __name__ == "__main__":
    main()
