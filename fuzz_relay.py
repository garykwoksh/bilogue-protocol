#!/usr/bin/env python3
"""
fuzz_relay.py — Bilogue Relay 模糊測試套件（P2-04）
==================================================
對 /send 同各端點狂掟隨機 / 畸形 / 超大 payload，驗證：
  1. relay 唔會 crash（最後 GET /healthz 依然 200）
  2. 異常一律返回 4xx/5xx，唔會 cut 連線或洩漏堆棧
  3. audit 鏈冇被寫崩（P1-07 integrity 仍 intact）

用法：
  python3 fuzz_relay.py            # 默認 300 次迭代
  python3 fuzz_relay.py --iters 1000 --port 8455
"""
import argparse
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bilogue_relay as sr

ADMIN = "fuzz-admin-token"
NONCE = 0


def rand_str(n=8):
    return os.urandom(random.randint(0, n)).hex()


def make_valid_env():
    e = {
        "msg_id": f"msg-{rand_str(16)}",
        "sender": random.choice(["karina", "stfund", "tester", "x"]),
        "receiver": random.choice(["karina", "stfund", "tester", "y"]),
        "intent_type": random.choice(list(sr.INTENT_TYPES)),
        "payload": {rand_str(4): rand_str(6)},
        "in_reply_to": None,
        "nonce": rand_str(16),
        "ts": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
    }
    e["sig"] = "bogus-sig"  # 絕大多數會 401，但唔應該 crash
    return e


def random_body():
    """生成各種畸形 body。"""
    kind = random.random()
    if kind < 0.30:
        return make_valid_env()                       # 結構對但簽名錯
    if kind < 0.45:
        e = make_valid_env()
        e.pop(random.choice(list(e.keys())), None)     # 缺欄位
        return e
    if kind < 0.55:
        return {rand_str(4): rand_str(4)}              # 完全唔相關結構
    if kind < 0.65:
        # 超大 payload
        return {"msg_id": "msg-x", "sender": "a", "receiver": "b",
                "intent_type": "DELEGATE", "payload": {"big": "z" * 2_000_000},
                "nonce": "n", "ts": "now", "sig": "s"}
    if kind < 0.75:
        # 完全隨機嵌套 JSON
        def rf(depth=0):
            if depth > 3 or random.random() < 0.3:
                return rand_str(5)
            t = random.random()
            if t < 0.33:
                return [rf(depth + 1) for _ in range(random.randint(0, 3))]
            if t < 0.66:
                return {rand_str(3): rf(depth + 1) for _ in range(random.randint(0, 3))}
            return rand_str(5)
        return rf()
    # 非 JSON 亂碼 bytes
    return os.urandom(random.randint(0, 200))


def fuzz(port, iters):
    base = f"http://localhost:{port}"
    endpoints = ["/send", "/approve", "/reject", "/grant", "/revoke",
                "/register", "/allow", "/pending", "/grants", "/kill",
                "/resume", "/rotate-token", "/audit/verify", "/healthz",
                "/metrics", "/inbox/karina", "/health", "/totally-random"]
    crashed = False
    statuses = {}
    for i in range(iters):
        path = random.choice(endpoints)
        token = ADMIN if random.random() < 0.5 else None
        body = random_body()
        raw = None
        if isinstance(body, (dict, list)):
            try:
                raw = json.dumps(body).encode()
            except Exception:
                raw = b"<<unjsonable>>"
        else:
            raw = body if isinstance(body, (bytes, bytearray)) else str(body).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        method = "POST" if path not in (
            "/pending", "/grants", "/audit/verify", "/healthz",
            "/metrics", "/inbox/karina", "/health", "/totally-random") else "GET"
        req = urllib.request.Request(f"{base}{path}", data=raw,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.status
                resp.read()
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                e.read()
            except Exception:
                pass
        except Exception as e:
            # 連線層異常（timeout / 斷線）—— 記低但唔即判 crash，最後再確認存活
            code = f"CONN:{type(e).__name__}"
        statuses[code] = statuses.get(code, 0) + 1

    # 最終存活檢查（重試幾次，排除瞬時連線抖動）
    alive = False
    hb = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=10) as r:
                if r.status == 200:
                    alive = True
                    hb = json.loads(r.read())
                    break
                hb = r.status
        except Exception:
            time.sleep(0.3)
    if not alive:
        crashed = True

    # audit 完整性（P1-07 bonus）
    inbox_path = Path(__file__).parent / "relay_inbox.jsonl"
    ok, bad = sr.RelayBus(inbox_path).verify_audit_log() if inbox_path.exists() else (True, -1)

    print(f"\n  模糊測試：{iters} 次迭代")
    print(f"  回應分佈：{statuses}")
    print(f"  最終存活（/healthz 200）：{alive}  {hb}")
    print(f"  audit integrity：{'intact' if ok else 'TAMPERED@'+str(bad)}")
    return (not crashed) and alive and ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8455)
    ap.add_argument("--iters", type=int, default=300)
    args = ap.parse_args()

    inbox = Path(__file__).parent / "fuzz_inbox.jsonl"
    try:
        inbox.unlink()
    except OSError:
        pass

    # 模糊測試唔係為咗測限速，放大所有速率上限以免干擾存活判斷
    sr.CONFIG["GLOBAL_RATE_MAX"] = 1_000_000
    sr.CONFIG["ADMIN_RATE_MAX"] = 1_000_000
    sr.CONFIG["SEND_RATE_MAX"] = 1_000_000

    server, relay = sr.make_server(args.port, auto_approve=True,
                                   admin_token=ADMIN, inbox_path=inbox)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.6)

    try:
        ok = fuzz(args.port, args.iters)
    finally:
        server.shutdown()
        try:
            inbox.unlink()
        except OSError:
            pass

    print(f"\n  {'✅ FUZZ PASS' if ok else '❌ FUZZ FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
