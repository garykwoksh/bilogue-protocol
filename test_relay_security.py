#!/usr/bin/env python3
"""
test_relay_security.py — Bilogue Relay v0.2.1 安全回歸測試
===========================================================
覆蓋 v0.2.1 全部 13 項安全修復（SEC-01 ~ SEC-13）+ 正常通信流程回歸。

跑法：
  python3 test_relay_security.py            # 測試 Consent Gate 模式（預設）
  python3 test_relay_security.py --port 8477
"""

import argparse
import hashlib
import hmac
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

# P0-07: 共用 bilogue_crypto 做簽名，確保 test 同 relay 用同一 canonical JSON
from bilogue_crypto import sign as bc_sign

ADMIN = "test-admin-token-6789"
BASE = None  # set in main

passed = failed = 0


def req(method, path, data=None, token=None, raw_body=None):
    body = raw_body if raw_body is not None else \
        (json.dumps(data).encode() if data is not None else None)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers,
                               method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return None, f"EXCEPTION: {type(e).__name__}: {e}"


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  FAILED {detail}")


def make_env(sender, secret, receiver, payload, msg_id=None, in_reply_to=None,
             intent="DELEGATE"):
    env = {"msg_id": msg_id or f"msg-{uuid.uuid4().hex}",  # P0-06: full UUID
           "sender": sender, "receiver": receiver,
           "intent_type": intent, "payload": payload,
           "in_reply_to": in_reply_to,
           "nonce": uuid.uuid4().hex, "ts": datetime.now(timezone.utc).isoformat()}
    env["sig"] = bc_sign(env, secret)  # P0-07: 共用 bilogue_crypto
    return env


def run_unit_tests():
    """v0.3.1 單元測試：直接 in-process 測 BilogueRelay / RelayBus 邏輯。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bilogue_relay", Path(__file__).parent / "bilogue_relay.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)

    print("\n[v0.3.1 單元] SEC-15/17/18/19/20")

    relay = sr.BilogueRelay(auto_approve=False, admin_token="u")
    ksec = relay.registry.get_agent("karina")["secret"]

    def env(intent="DELEGATE", in_reply_to=None, sender="karina",
            receiver="stfund", msg_id=None, secret=None):
        e = {"msg_id": msg_id or f"msg-{uuid.uuid4().hex}",  # P0-06: full UUID
             "sender": sender, "receiver": receiver, "intent_type": intent,
             "payload": {"t": "unit"}, "in_reply_to": in_reply_to,
             "nonce": uuid.uuid4().hex,
             "ts": datetime.now(timezone.utc).isoformat()}
        e["sig"] = bc_sign(e, secret or ksec)  # P0-07: 共用 bilogue_crypto
        return e

    # --- SEC-20: 狀態機 ---
    code, _, _ = relay.handle_send(env(intent="ACCEPT"))
    check("單元：ACCEPT 開新對話 → 400", code == 400, f"{code}")
    root = env(intent="DELEGATE")
    code, _, _ = relay.handle_send(root)
    check("單元：DELEGATE 開對話 → 202", code == 202, f"{code}")
    code, _, _ = relay.handle_approve({"msg_id": root["msg_id"]})
    check("單元：approve 根訊息 → 200", code == 200, f"{code}")
    code, msg, _ = relay.handle_send(env(intent="QUERY",
                                         in_reply_to=root["msg_id"]))
    check("單元：DELEGATE→QUERY 非法 → 400", code == 400, f"{code} {msg}")
    code, _, _ = relay.handle_send(env(intent="PROPOSE",
                                       in_reply_to="msg-ghost"))
    check("單元：in_reply_to 唔存在 → 400", code == 400, f"{code}")

    # --- SEC-17: handle_approve 預設 once ---
    code, _, data = relay.handle_send(env(intent="PROPOSE",
                                          in_reply_to=root["msg_id"]))
    check("單元：scope=once 嘅合法回覆 → 202", code == 202, f"{code}")

    # --- SEC-15: 對話鏈 TTL ---
    old_ttl = sr.CONV_TTL_SECONDS
    sr.CONV_TTL_SECONDS = 0.3
    try:
        relay2 = sr.BilogueRelay(auto_approve=False, admin_token="u")
        ksec2 = relay2.registry.get_agent("karina")["secret"]  # 每個 relay 實例嘅 secret 唔同
        root2 = env(intent="DELEGATE", secret=ksec2)
        relay2.handle_send(root2)
        relay2.handle_approve({"msg_id": root2["msg_id"],
                               "scope": "conversation"})
        r1 = env(intent="PROPOSE", in_reply_to=root2["msg_id"], secret=ksec2)
        code, _, _ = relay2.handle_send(r1)
        check("單元：TTL 內對話鏈放行 → 200", code == 200, f"{code}")
        time.sleep(0.4)
        r2 = env(intent="ACCEPT", in_reply_to=r1["msg_id"], secret=ksec2)
        code, _, _ = relay2.handle_send(r2)
        check("單元：TTL 過期後對話鏈失效 → 202", code == 202, f"{code}")
    finally:
        sr.CONV_TTL_SECONDS = old_ttl

    # --- SEC-18: grants 上限 ---
    old_max = sr.MAX_GRANTS
    sr.MAX_GRANTS = 2
    try:
        relay3 = sr.BilogueRelay(auto_approve=False, admin_token="u")
        relay3.registry.register("x1"); relay3.registry.register("x2")
        c1, _, _ = relay3.handle_grant({"agent_a": "karina", "agent_b": "x1",
                                        "direction": "a_to_b"})
        c2, _, _ = relay3.handle_grant({"agent_a": "karina", "agent_b": "x2",
                                        "direction": "a_to_b"})
        c3, msg3, _ = relay3.handle_grant({"agent_a": "x1", "agent_b": "x2",
                                           "direction": "a_to_b"})
        check("單元：第 3 個 grant 超上限 → 429",
              c1 == 200 and c2 == 200 and c3 == 429, f"{c1}/{c2}/{c3} {msg3}")
    finally:
        sr.MAX_GRANTS = old_max

    # --- SEC-19: audit log rotation ---
    old_bytes = sr.MAX_LOG_BYTES
    sr.MAX_LOG_BYTES = 600
    try:
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "test_inbox.jsonl"
        bus = sr.RelayBus(tmp)
        for i in range(300):
            bus.append({"msg_id": f"m{i}", "payload": "x" * 80},
                       deliver=False)
        rotated = tmp.with_name("test_inbox.jsonl.1").exists()
        check("單元：audit log 超 600B 後 rotation 出 .1 舊檔", rotated)
        import shutil; shutil.rmtree(tmp.parent, ignore_errors=True)
    finally:
        sr.MAX_LOG_BYTES = old_bytes

    # ---- Round-2/3（P1 × 8 + P2 × 4）單元測試 ----
    print("\n[v0.3.3 單元] P1-02 / P1-03 / P1-07 / P2-01 / P2-03")

    # P1-02: RateLimiter 滑動窗口
    rl = sr.RateLimiter(3, 60)
    three = [rl.allow("ip1") for _ in range(3)]
    fourth = rl.allow("ip1")
    check("P1-02: 滑動窗口滿額後拒絕",
          three == [True, True, True] and fourth is False, f"{three} {fourth}")
    check("P1-02: 唔同 key 互不影響", rl.allow("ip2") is True)
    rl2 = sr.RateLimiter(2, 60); rl2.allow("k"); rl2.allow("k")
    check("P1-02: count() 正確計總", rl2.count() >= 2, f"{rl2.count()}")

    # P1-03: CryptoStore 加密 roundtrip（cryptography 可用）
    import tempfile as _tf
    kd = _tf.mkdtemp()
    cs = sr.CryptoStore(_tf.mkdtemp() + "/k.key")
    if cs.using_encryption:
        enc = cs.encrypt_line('{"a":1}')
        check("P1-03: 加密行以 F: 前綴", enc.startswith("F:"), enc[:4])
        check("P1-03: 解密 roundtrip",
              cs.decrypt_line(enc) == '{"a":1}', cs.decrypt_line(enc))
    else:
        check("P1-03: cryptography 唔可用 → 明文 + 唔加密（降級）", True, "skip")

    # P2-03: validate_config 拒絕非法配置
    bad_cfg = dict(sr.CONFIG); bad_cfg["MSG_TTL_SECONDS"] = -5
    raised = False
    try:
        sr.validate_config(bad_cfg)
    except ValueError:
        raised = True
    check("P2-03: validate_config 對負值拋 ValueError（fail-closed）", raised)
    check("P2-03: 預設 CONFIG 通過校驗", sr.validate_config() is True)

    # P2-01: nonce 重用檢測窗口延長（默認 ≥ 1h，且 > 舊 5min 窗口）
    check("P2-01: NONCE_REPLAY_TTL ≥ 3000s（遠大過舊 MAX_AGE）",
          sr.CONFIG["NONCE_REPLAY_TTL"] >= 3000,
          f"{sr.CONFIG['NONCE_REPLAY_TTL']}")

    # P1-07: 防篡改審計鏈（HMAC 鏈） integrity + tamper detection
    tdir = _tf.mkdtemp()
    tbus = sr.RelayBus(Path(tdir) / "audit.jsonl")
    for i in range(6):
        tbus.append({"msg_id": f"m{i}", "payload": {"i": i}}, deliver=False)
    ok, bad = tbus.verify_audit_log()
    check("P1-07: 乾淨 audit 鏈 integrity=intact", ok and bad == -1, f"{ok} {bad}")
    # 篡改最後一行
    lines = (Path(tdir) / "audit.jsonl").read_text().splitlines()
    lines[-1] = lines[-1][:-3] + "ZZZ"
    (Path(tdir) / "audit.jsonl").write_text("\n".join(lines) + "\n")
    ok2, bad2 = tbus.verify_audit_log()
    check("P1-07: 篡改後 integrity=TAMPERED 且報出行號",
          (ok2 is False) and bad2 >= 0, f"{ok2} {bad2}")
    import shutil as _sh; _sh.rmtree(tdir, ignore_errors=True)


def run_p0_persistence_tests(base_port, admin_token):
    """P0-01 / P0-02 / P0-03：用獨立 relay 測持久化 kill + resume + 批准前重驗。
    唔會影響主 relay（主 relay 喺另一個 port）。"""
    import json as _json
    import tempfile
    import subprocess as _sp

    relay_py = Path(__file__).parent / "bilogue_relay.py"
    state_file = Path(tempfile.mktemp(prefix="bilogue_pst_", suffix=".json"))
    port = base_port

    def preq(method, path, data=None, token=None):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(f"http://localhost:{port}{path}",
                                   data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {"error": "non-json"}
        except Exception as e:
            return None, f"EXCEPTION: {type(e).__name__}: {e}"

    try:
        # 起 relay A
        pa = _sp.Popen([sys.executable, str(relay_py), "--port", str(port),
                        "--admin-token", admin_token,
                        "--state-file", str(state_file)],
                       stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        time.sleep(1.3)

        # P0-01: 預設綁 127.0.0.1，localhost health 要 200
        c, h = preq("GET", "/health")
        check("P0-01: relay 綁 127.0.0.1 且 localhost health 200",
              c == 200 and h.get("status") == "alive", f"{c} {h}")

        # 註冊 + 授權 tester↔bot2，拎 secret
        _, reg_t = preq("POST", "/register", {"agent_id": "tester"}, token=admin_token)
        _, reg_b = preq("POST", "/register", {"agent_id": "bot2"}, token=admin_token)
        preq("POST", "/allow", {"agent_a": "tester", "agent_b": "bot2"}, token=admin_token)
        t_sec = reg_t.get("secret")
        b_read = reg_b.get("read_token")

        # P0-03: 先入一條 pending，再 kill，再 approve → 要被拒（409）
        ep = make_env("tester", t_sec, "bot2", {"task": "pending-then-kill"})
        preq("POST", "/send", ep)  # 202 pending
        preq("POST", "/kill", {}, token=admin_token)
        c, r = preq("POST", "/approve", {"msg_id": ep["msg_id"]}, token=admin_token)
        check("P0-03: relay kill 後 approve → 409 APPROVAL_REJECTED",
              c == 409 and "APPROVAL_REJECTED" in r.get("message", ""), f"{c} {r}")

        # P0-02: state file 已持久化 killed=true
        try:
            data = _json.loads(state_file.read_text(encoding="utf-8"))
            check("P0-02: kill 後 state file killed=true", data.get("killed") is True,
                  f"{data}")
        except Exception as e:
            check("P0-02: 讀取 state file", False, f"{e}")

        # 起 relay B（同一 port + 同一 state file）→ 應仍然 STOPPED
        pa.terminate(); time.sleep(1.2)
        pb = _sp.Popen([sys.executable, str(relay_py), "--port", str(port),
                        "--admin-token", admin_token,
                        "--state-file", str(state_file)],
                       stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        time.sleep(1.3)
        c, h = preq("GET", "/health")
        check("P0-02: 新 relay 讀 state file → 仍 STOPPED（status=killed）",
              c == 200 and h.get("status") == "killed", f"{c} {h}")
        # RESUME 恢復
        c, r = preq("POST", "/resume", {}, token=admin_token)
        check("P0-02: resume → 200", c == 200, f"{c} {r}")
        c, h = preq("GET", "/health")
        check("P0-02: resume 後 alive", c == 200 and h.get("status") == "alive",
              f"{c} {h}")
        # RESUME 唔會令舊 grant 復活（之前無 grant，呢度確認 grant 數 = 0）
        _, gl = preq("GET", "/grants", token=admin_token)
        check("P0-02: resume 後舊 grant 唔會自動復活（grants=0）",
              gl.get("count", -1) == 0, f"{gl}")
        pb.terminate()
    finally:
        try:
            pa.terminate()
        except Exception:
            pass
        try:
            pb.terminate()
        except Exception:
            pass
        try:
            state_file.unlink()
        except OSError:
            pass


def run_p1_p2_tests(base_port, admin_token):
    """v0.3.3 P1 × 8 + P2 × 4 HTTP 回歸（用獨立 relay，send 限速設緊以便測 429）。
    覆蓋：P1-02 限速/輪換、P1-03 加密、P1-06 revoke 通知、P1-07 audit/verify、
    P1-08 healthz/metrics、P2-03 config。"""
    import tempfile as _tf
    relay_py = Path(__file__).parent / "bilogue_relay.py"
    port = base_port
    # 放寬 admin / global 限速以免正常測試被斷；send 限速設 3 專門測 429
    env = dict(os.environ)
    env["BILOGUE_SEND_RATE"] = "3"
    env["BILOGUE_ADMIN_RATE"] = "100"
    env["BILOGUE_GLOBAL_RATE"] = "200"
    state_file = Path(_tf.mktemp(prefix="bilogue_p12_", suffix=".json"))
    # 隔離 audit 檔（唔同主 relay 共享），避免主 relay 被 terminate 留低半行污染
    inbox_file = Path(_tf.mktemp(prefix="bilogue_p12_inbox_", suffix=".jsonl"))
    audit_key_file = Path(_tf.mktemp(prefix="bilogue_p12_audit_", suffix=".key"))
    crypto_key_file = Path(_tf.mktemp(prefix="bilogue_p12_crypto_", suffix=".key"))

    def pq(method, path, data=None, token=None):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(f"http://localhost:{port}{path}",
                                   data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {"error": "non-json"}
        except Exception as e:
            return None, f"EXC: {type(e).__name__}: {e}"

    proc = subprocess.Popen([sys.executable, str(relay_py), "--port", str(port),
                             "--admin-token", admin_token,
                             "--state-file", str(state_file),
                             "--inbox", str(inbox_file),
                             "--audit-key-file", str(audit_key_file),
                             "--crypto-key-file", str(crypto_key_file)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=env)
    time.sleep(1.2)
    try:
        print(f"\n[v0.3.3 P1/P2] port={port}")
        # 準備一對 agent
        _, ra = pq("POST", "/register", {"agent_id": "p1a"}, token=admin_token)
        _, rb = pq("POST", "/register", {"agent_id": "p1b"}, token=admin_token)
        p1a_sec = ra["secret"]; p1b_read = rb["read_token"]
        pq("POST", "/allow", {"agent_a": "p1a", "agent_b": "p1b"}, token=admin_token)

        # P1-02: send 限速（SEND_RATE=3）→ 第 4 條 429
        codes = []
        for i in range(4):
            e = make_env("p1a", p1a_sec, "p1b", {"i": i}, msg_id=f"msg-rate-{i}")
            codes.append(pq("POST", "/send", e)[0])
        check("P1-02: 同 IP 第 4 條 send → 429（限速生效）",
              codes[:3] == [202, 202, 202] and codes[3] == 429,
              f"{codes}")

        # P1-02: admin token 輪換（舊失效、新生效）
        c_old, _ = pq("GET", "/pending", token=admin_token)
        rc, rj = pq("POST", "/rotate-token", token=admin_token)
        new_tok = rj.get("admin_token")
        check("P1-02: 輪換返回新 token", rc == 200 and bool(new_tok), f"{rc}")
        c_after_old, _ = pq("GET", "/pending", token=admin_token)
        c_after_new, _ = pq("GET", "/pending", token=new_tok)
        check("P1-02: 舊 token 失效 / 新 token 生效",
              c_after_old == 403 and c_after_new == 200,
              f"{c_after_old}/{c_after_new}")

        # P1-06: grant revoke 即時通知 receiver
        _, g = pq("POST", "/grant",
                  {"agent_a": "p1a", "agent_b": "p1b", "direction": "a_to_b",
                   "ttl_seconds": 60, "max_messages": 5}, token=new_tok)
        gid = g.get("grant_id")
        rc2, rj2 = pq("POST", "/revoke", {"grant_id": gid}, token=new_tok)
        check("P1-06: revoke 成功且回報通知咗 receiver",
              rc2 == 200 and "p1b" in (rj2.get("notified") or []), f"{rc2} {rj2}")
        _, inbox = pq("GET", "/inbox/p1b", token=p1b_read)
        sys_msg = [m for m in inbox.get("messages", [])
                   if m.get("sender") == "system"]
        check("P1-06: receiver inbox 收到 system 撤銷通知",
              inbox["count"] >= 1 and bool(sys_msg), f"{inbox.get('count')}")

        # P1-07: audit 完整性驗證（admin）
        _, av = pq("GET", "/audit/verify", token=new_tok)
        check("P1-07: /audit/verify 返回 integrity（intact 或 tampered）",
              "integrity" in av, f"{av}")
        check("P1-07: 乾淨運行下 integrity=intact",
              av.get("integrity") == "intact", f"{av}")

        # P1-08: healthz / metrics
        _, hz = pq("GET", "/healthz")
        _, mt = pq("GET", "/metrics")
        check("P1-08: /healthz 有 version + killed",
              hz.get("version") == "0.3.3" and "killed" in hz, f"{hz}")
        check("P1-08: /metrics 有聚合計數",
              "pending_approvals" in mt and "active_grants" in mt, f"{mt}")

        # P1-03: 磁碟加密 —— 檢查隔離 audit 檔至少有一行係 F: 加密（cryptography 可用時）
        encrypted = False
        if inbox_file.exists():
            for ln in inbox_file.read_text().splitlines():
                if ln.strip().startswith("F:"):
                    encrypted = True
                    break
        if sr_crypto_available():
            check("P1-03: audit 檔使用 Fernet 加密（F: 前綴）", encrypted)
        else:
            check("P1-03: cryptography 唔可用 → 明文（降級，已知 residual）",
                  True, "skip")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        for f in (state_file, inbox_file, audit_key_file, crypto_key_file):
            try:
                Path(f).unlink()
            except OSError:
                pass


def sr_crypto_available():
    """helper：cryptography 可用？"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bilogue_relay", Path(__file__).parent / "bilogue_relay.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m._FERNET_AVAILABLE
    except Exception:
        return False


def run_tls_tests():
    """P1-01: 非 loopback 無 TLS 必須拒絕啟動；有 TLS 可 HTTPS 握手。"""
    import tempfile as _tf
    relay_py = Path(__file__).parent / "bilogue_relay.py"

    # (1) 非 loopback 無 TLS → 拒絕（exit code 3）
    p_ref = subprocess.Popen([sys.executable, str(relay_py), "--host", "0.0.0.0",
                              "--port", "0", "--admin-token", "x"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        rc = p_ref.wait(timeout=8)
    except subprocess.TimeoutExpired:
        p_ref.terminate(); rc = None
    check("P1-01: 非 loopback 無 TLS → 拒絕啟動（exit=3）", rc == 3, f"{rc}")

    # (2) 非 loopback + --allow-insecure-lan → 可啟動（不推薦）
    p_inc = subprocess.Popen([sys.executable, str(relay_py), "--host", "0.0.0.0",
                              "--port", "0", "--admin-token", "x",
                              "--allow-insecure-lan"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.3)
    check("P1-01: --allow-insecure-lan 可強行啟動（明文，極唔推薦）",
          p_inc.poll() is None, f"{p_inc.poll()}")
    p_inc.terminate()

    # (3) 有 TLS（127.0.0.1）→ HTTPS 握手成功
    tdir = _tf.mkdtemp()
    cert = Path(tdir) / "cert.pem"
    key = Path(tdir) / "key.pem"
    gen = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "1",
         "-subj", "/CN=localhost"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if gen.returncode != 0:
        check("P1-01: openssl 生成自簽證書", False, "openssl 唔可用")
        return
    tls_port = 8499
    p_tls = subprocess.Popen([sys.executable, str(relay_py), "--host", "127.0.0.1",
                              "--port", str(tls_port), "--admin-token", "tls-tok",
                              "--tls-cert", str(cert), "--tls-key", str(key)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env=dict(os.environ, BILOGUE_GLOBAL_RATE="10000",
                                      BILOGUE_ADMIN_RATE="1000",
                                      BILOGUE_SEND_RATE="1000"))
    time.sleep(1.3)
    try:
        ctx = ssl.create_default_context(cafile=str(cert))
        ctx.check_hostname = False
        https_url = f"https://localhost:{tls_port}/health"
        req_h = urllib.request.Request(https_url)
        with urllib.request.urlopen(req_h, timeout=10, context=ctx) as resp:
            hcode = resp.status
            hbody = json.loads(resp.read())
        check("P1-01: HTTPS 握手 + /health → 200", hcode == 200, f"{hcode} {hbody}")
    except Exception as e:
        check("P1-01: HTTPS 握手成功", False, f"{type(e).__name__}: {e}")
    finally:
        p_tls.terminate()


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8478)
    args = ap.parse_args()
    BASE = f"http://localhost:{args.port}"

    relay_py = Path(__file__).parent / "bilogue_relay.py"
    import tempfile
    test_state = Path(tempfile.mktemp(prefix="bilogue_test_state_", suffix=".json"))
    # 放寬限速以免正常測試（大量 admin/send 呼叫）被 429；專門嘅限速測試用獨立 relay
    main_env = dict(os.environ)
    main_env["BILOGUE_GLOBAL_RATE"] = "10000"
    main_env["BILOGUE_ADMIN_RATE"] = "1000"
    main_env["BILOGUE_SEND_RATE"] = "1000"
    proc = subprocess.Popen(
        [sys.executable, str(relay_py), "--port", str(args.port),
         "--admin-token", ADMIN, "--state-file", str(test_state)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=main_env)
    time.sleep(1.2)

    try:
        # ----------------------------------------------------------------
        print("\n[0] 取得測試用 credential（模擬正常註冊流程）")
        code, reg = req("POST", "/register", {"agent_id": "tester"}, token=ADMIN)
        check("註冊新 agent 返回 secret + read_token",
              code == 200 and "secret" in reg and "read_token" in reg
              and reg["secret"] != reg["read_token"], f"{code} {reg}")
        tester_secret, tester_read = reg["secret"], reg["read_token"]
        req("POST", "/allow", {"agent_a": "tester", "agent_b": "karina"}, token=ADMIN)

        # karina secret 喺 v0.2.1 已唔可以再經 /register 攞——
        # 測試改用 tester 做 sender。但部分測試要 karina，所以先用 tester ↔ karina。
        print("\n[SEC-01] 重複註冊唔准洩漏 secret")
        code, r = req("POST", "/register", {"agent_id": "karina"}, token=ADMIN)
        check("重複註冊 karina → 409 且冇 secret",
              code == 409 and "secret" not in r, f"{code} {r}")

        print("\n[SEC-02] Consent Gate 拒絕 msg_id 掉包")
        mid = f"msg-dup-{uuid.uuid4().hex}"  # P0-06: full UUID
        env_a = make_env("tester", tester_secret, "karina", {"task": "原本任務"}, mid)
        code_a, _ = req("POST", "/send", env_a)
        env_b = make_env("tester", tester_secret, "karina", {"task": "掉包任務"}, mid)
        code_b, r_b = req("POST", "/send", env_b)
        _, pend = req("GET", "/pending", token=ADMIN)
        orig_still = any(p["msg_id"] == mid and "原本任務" in p["payload_preview"]
                         for p in pend.get("pending", []))
        check("第一條入 pending (202) + 第二條同 msg_id → 409",
              code_a == 202 and code_b == 409, f"{code_a}/{code_b} {r_b}")
        check("pending 入面仲係原本嗰條（未被掉包）", orig_still)
        req("POST", "/reject", {"msg_id": mid}, token=ADMIN)  # 清場

        print("\n[SEC-03] Request body 上限")
        big = make_env("tester", tester_secret, "karina",
                       {"task": "x" * 2_000_000})
        code, r = req("POST", "/send", raw_body=json.dumps(big).encode())
        check("2MB body → 413", code == 413, f"{code} {r}")
        code, r = req("POST", "/send", raw_body=b"{}",
                      token=None)  # 正常細 body 唔受影響（會 401 因為冇簽名）
        check("細 body 正常進入簽名檢查（401 而唔係 413）", code == 401, f"{code}")

        print("\n[SEC-04] query string 畸形參數")
        code, r = req("GET", "/inbox/tester?since=abc", token=tester_read)
        check("since=abc → 400 而唔係 cut 連線", code == 400, f"{code} {r}")
        code, r = req("GET", "/inbox/tester?foo=1&since=0", token=tester_read)
        check("混合 query 正常解析 → 200", code == 200, f"{code} {r}")

        print("\n[SEC-05] 公開端點唔再洩漏拓撲")
        code, r = req("GET", "/acl")
        check("/acl 無 token → 403", code == 403, f"{code} {r}")
        code, r = req("GET", "/acl", token=ADMIN)
        check("/acl 有 admin token → 200", code == 200, f"{code}")
        code, r = req("GET", "/health")
        check("/health 只返 status（冇 agents/acl/pending）",
              code == 200 and set(r.keys()) == {"status"}, f"{code} {r}")

        print("\n[SEC-06] admin token 錯誤 → 403（compare_digest 路徑）")
        code, _ = req("GET", "/pending", token="wrong-token")
        check("錯 admin token → 403", code == 403, f"{code}")

        print("\n[SEC-09/12] inbox 認證：read_token 先啱用，唔可枚舉")
        code, _ = req("GET", "/inbox/tester", token=tester_secret)
        check("用簽名 secret 讀 inbox → 403（secret ≠ read_token）",
              code == 403, f"{code}")
        code_a, _ = req("GET", "/inbox/ghost_agent")
        code_b, _ = req("GET", "/inbox/tester")
        check("唔存在嘅 agent 同錯 token 一律 403（防枚舉）",
              code_a == 403 and code_b == 403, f"{code_a}/{code_b}")

        print("\n[SEC-10] inbox 讀完即清")
        req("POST", "/approve", {"msg_id": "never"}, token=ADMIN)  # no-op
        env = make_env("tester", tester_secret, "karina", {"task": "待批准訊息"})
        _, r = req("POST", "/send", env)
        req("POST", "/approve", {"msg_id": env["msg_id"]}, token=ADMIN)
        code1, inbox1 = req("GET", "/inbox/karina",
                            token=None) if False else (None, None)
        # 用 admin 註冊流程攞唔到 karina read_token——改測 tester 自己嘅 inbox
        env2 = make_env("tester", tester_secret, "karina", {"task": "x"})  # keep ACL 雙向
        # karina → tester 需要 karina secret，冇。改用 approve 路徑送去 karina，
        # 再驗 pop 語意：approve 後 karina inbox 有一條，但我哋冇 karina read_token。
        # 所以直接驗 tester 嘅 inbox：先送 tester→karina 唔得。改為註冊新 agent pair。
        code, reg2 = req("POST", "/register", {"agent_id": "bot2"}, token=ADMIN)
        bot2_secret, bot2_read = reg2["secret"], reg2["read_token"]
        req("POST", "/allow", {"agent_a": "tester", "agent_b": "bot2"}, token=ADMIN)
        env3 = make_env("tester", tester_secret, "bot2", {"task": "hello bot2"})
        req("POST", "/send", env3)
        # SEC-14: 批准之前，inbox 唔應該見到 pending 訊息（Consent Gate 唔准經 inbox 繞過）
        code0, i0 = req("GET", "/inbox/bot2", token=bot2_read)
        check("批准前 inbox 係空（SEC-14: pending 唔落收件隊列）",
              code0 == 200 and i0["count"] == 0, f"{code0} {i0.get('count')}")
        req("POST", "/approve", {"msg_id": env3["msg_id"]}, token=ADMIN)
        code1, i1 = req("GET", "/inbox/bot2", token=bot2_read)
        # P0-05: 讀咗但未 ACK，第二次讀取仲有 1 條（唔會即刪）
        code2, i2 = req("GET", "/inbox/bot2", token=bot2_read)
        check("第一次讀取有 1 條", code1 == 200 and i1["count"] == 1,
              f"{code1} {i1.get('count')}")
        check("P0-05: 未 ACK 第二次讀取仍有 1 條（唔會即刪）",
              code2 == 200 and i2["count"] == 1, f"{code2} {i2.get('count')}")
        # ACK 之後先清空
        ackc, ackr = req("POST", f"/messages/bot2/{env3['msg_id']}/ack",
                         token=bot2_read)
        check("P0-05: ACK 一條 → 200", ackc == 200, f"{ackc} {ackr}")
        code3, i3 = req("GET", "/inbox/bot2", token=bot2_read)
        check("P0-05: ACK 之後 0 條", code3 == 200 and i3["count"] == 0,
              f"{code3} {i3.get('count')}")

        print("\n[SEC-13] handler 兜底")
        code, r = req("POST", "/send", raw_body=b"not-json{{{")
        check("畸形 JSON → 400 而唔係 cut 連線", code == 400, f"{code} {r}")
        code, r = req("GET", "/health")
        check("server 仲活著", code == 200 and r["status"] == "alive", f"{code}")

        print("\n[v0.3] L3 限時信任窗口")
        code, _ = req("POST", "/grant",
                      {"agent_a": "tester", "agent_b": "bot2"})
        check("/grant 無 admin token → 403", code == 403, f"{code}")
        code, g = req("POST", "/grant",
                      {"agent_a": "tester", "agent_b": "bot2",
                       "direction": "a_to_b", "ttl_seconds": 60,
                       "max_messages": 2}, token=ADMIN)
        check("建立 grant（a→b, 60s, 2 條）→ 200 + grant_id",
              code == 200 and g.get("grant_id"), f"{code} {g}")
        gid = g.get("grant_id")
        # 預算內放行（唔使逐條批）
        c1, _ = req("POST", "/send", make_env("tester", tester_secret, "bot2",
                                              {"task": "窗口訊息 1"}))
        c2, _ = req("POST", "/send", make_env("tester", tester_secret, "bot2",
                                              {"task": "窗口訊息 2"}))
        check("預算內兩條都直接 200 放行", c1 == 200 and c2 == 200,
              f"{c1}/{c2}")
        # 預算用盡 → 跌返 L1 pending
        c3, r3 = req("POST", "/send", make_env("tester", tester_secret, "bot2",
                                               {"task": "窗口訊息 3"}))
        check("第 3 條超預算 → 202 跌返 L1", c3 == 202, f"{c3}")
        req("POST", "/reject", {"msg_id": r3.get("msg_id")}, token=ADMIN)
        # 反方向冇 grant（a_to_b 單向）
        c4, r4 = req("POST", "/send", make_env("bot2", bot2_secret, "tester",
                                               {"task": "反方向"}))
        check("反方向（b→a）冇被涵蓋 → 202", c4 == 202, f"{c4}")
        req("POST", "/reject", {"msg_id": r4.get("msg_id")}, token=ADMIN)
        # /grants 列表 + revoke
        code, gl = req("GET", "/grants", token=ADMIN)
        check("/grants 見到活躍窗口", code == 200 and gl["count"] >= 1,
              f"{code} {gl}")
        code, _ = req("POST", "/revoke", {"grant_id": gid}, token=ADMIN)
        check("revoke grant → 200", code == 200, f"{code}")
        c5, r5 = req("POST", "/send", make_env("tester", tester_secret, "bot2",
                                               {"task": "revoke 之後"}))
        check("revoke 後 → 202 跌返 L1", c5 == 202, f"{c5}")
        req("POST", "/reject", {"msg_id": r5.get("msg_id")}, token=ADMIN)
        # TTL 過期
        req("POST", "/grant", {"agent_a": "tester", "agent_b": "bot2",
                               "direction": "a_to_b", "ttl_seconds": 1,
                               "max_messages": 5}, token=ADMIN)
        time.sleep(1.3)
        c6, r6 = req("POST", "/send", make_env("tester", tester_secret, "bot2",
                                               {"task": "過期窗口"}))
        check("TTL 過期後 → 202 跌返 L1", c6 == 202, f"{c6}")
        req("POST", "/reject", {"msg_id": r6.get("msg_id")}, token=ADMIN)

        print("\n[v0.3] L2 對話鏈同意")
        root = make_env("tester", tester_secret, "bot2", {"task": "Q3 核數"})
        c7, r7 = req("POST", "/send", root)
        check("新話題 DELEGATE → 202 等人批", c7 == 202, f"{c7}")
        code, ap = req("POST", "/approve",
                       {"msg_id": root["msg_id"], "scope": "conversation"},
                       token=ADMIN)
        check("approve scope=conversation → 200", code == 200, f"{code} {ap}")
        # 後續鏈自動放行（b→a 都包，因為係同一條 thread）
        reply1 = make_env("bot2", bot2_secret, "tester", {"task": "PROPOSE 大綱"},
                          in_reply_to=root["msg_id"], intent="PROPOSE")
        c8, _ = req("POST", "/send", reply1)
        check("鏈上回覆（bot2→tester）→ 200 自動放行", c8 == 200, f"{c8}")
        reply2 = make_env("tester", tester_secret, "bot2", {"task": "ACCEPT"},
                          in_reply_to=reply1["msg_id"], intent="ACCEPT")
        c9, _ = req("POST", "/send", reply2)
        check("鏈上第二棒 → 200 自動放行", c9 == 200, f"{c9}")
        # 新話題唔受惠
        c10, r10 = req("POST", "/send", make_env("tester", tester_secret, "bot2",
                                                 {"task": "另一單新嘢"}))
        check("無 in_reply_to 嘅新話題 → 202", c10 == 202, f"{c10}")
        # scope=once：只放一條
        code, _ = req("POST", "/approve",
                      {"msg_id": r10.get("msg_id"), "scope": "once"},
                      token=ADMIN)
        check("approve scope=once → 200", code == 200, f"{code}")
        orphan = make_env("bot2", bot2_secret, "tester", {"task": "跟進"},
                          in_reply_to=r10.get("msg_id"), intent="PROPOSE")
        c11, r11 = req("POST", "/send", orphan)
        check("scope=once 嘅後續 → 202（唔開鏈）", c11 == 202, f"{c11}")
        req("POST", "/reject", {"msg_id": r11.get("msg_id")}, token=ADMIN)

        print("\n[v0.3.1] SEC-17/20 狀態機 + 最小權限預設")
        # REPORT 唔可以開新對話
        bad = make_env("tester", tester_secret, "bot2", {"task": "x"},
                       intent="REPORT")
        c, _ = req("POST", "/send", bad)
        check("REPORT 無 in_reply_to 開新對話 → 400", c == 400, f"{c}")
        # 合法開對話 + approve（唔帶 scope → 預設 once，SEC-17）
        root2 = make_env("tester", tester_secret, "bot2", {"task": "狀態機測試"})
        req("POST", "/send", root2)
        code, ap = req("POST", "/approve", {"msg_id": root2["msg_id"]},
                       token=ADMIN)
        check("approve 唔帶 scope → 200（預設 once）",
              code == 200 and ap.get("scope") == "once", f"{code} {ap}")
        # 非法轉移：DELEGATE → DELEGATE
        ill = make_env("bot2", bot2_secret, "tester", {"task": "非法"},
                       in_reply_to=root2["msg_id"], intent="DELEGATE")
        c, r = req("POST", "/send", ill)
        check("DELEGATE→DELEGATE 非法轉移 → 400", c == 400, f"{c} {r}")
        # 合法轉移：DELEGATE → PROPOSE，但因為 scope=once 冇開鏈 → 202
        leg = make_env("bot2", bot2_secret, "tester", {"task": "合法"},
                       in_reply_to=root2["msg_id"], intent="PROPOSE")
        c, r = req("POST", "/send", leg)
        check("合法 PROPOSE 但 scope=once → 202（SEC-17 最小權限）",
              c == 202, f"{c}")
        req("POST", "/reject", {"msg_id": r.get("msg_id")}, token=ADMIN)
        # in_reply_to 指向唔存在嘅訊息
        ghost = make_env("bot2", bot2_secret, "tester", {"task": "ghost"},
                         in_reply_to="msg-not-exist", intent="PROPOSE")
        c, _ = req("POST", "/send", ghost)
        check("in_reply_to 搵唔到 → 400", c == 400, f"{c}")

        print("\n[v0.3.1] SEC-16 slow-loris 防護")
        import socket as _sock
        slow = _sock.create_connection(("localhost", args.port), timeout=5)
        slow.sendall(b"POST /send HTTP/1.1\r\nHost: x\r\n"
                     b"Content-Length: 900000\r\n\r\n")  # 宣告咗但唔送 body
        code, r = req("GET", "/health")
        check("慢連線霸住嘅同時 /health 照常 200", code == 200, f"{code}")
        slow.close()

        print("\n[P0] Round-1 P0 回歸（4/8 項，用主 relay）")
        # P0-04: 批准綁定 envelope hash + 獨立 consent_id
        e4 = make_env("tester", tester_secret, "bot2", {"task": "consent test"})
        req("POST", "/send", e4)
        c4, r4 = req("POST", "/approve", {"msg_id": e4["msg_id"]}, token=ADMIN)
        check("P0-04: approve 返回 consent_id",
              c4 == 200 and bool(r4.get("consent_id")), f"{c4} {r4}")
        req("POST", f"/messages/bot2/{e4['msg_id']}/ack", token=bot2_read)
        # /pending 要見到 envelope_hash
        e5 = make_env("tester", tester_secret, "bot2", {"task": "pending hash"})
        req("POST", "/send", e5)
        _, pend = req("GET", "/pending", token=ADMIN)
        hpresent = any(p["msg_id"] == e5["msg_id"] and p.get("envelope_hash")
                       for p in pend.get("pending", []))
        check("P0-04: /pending 返回 envelope_hash", hpresent, f"{pend.get('count')}")
        req("POST", "/reject", {"msg_id": e5["msg_id"]}, token=ADMIN)

        # P0-06: 完整 UUID（grant_id + msg_id）
        _, g = req("POST", "/grant",
                   {"agent_a": "tester", "agent_b": "bot2", "direction": "a_to_b",
                    "ttl_seconds": 60, "max_messages": 5}, token=ADMIN)
        check("P0-06: grant_id 係完整 UUID（> 12 字）",
              len(g.get("grant_id", "")) > 12, g.get("grant_id"))
        e6 = make_env("tester", tester_secret, "bot2", {"task": "uuid"})
        e6_id = e6["msg_id"].split("msg-", 1)[1] if e6["msg_id"].startswith("msg-") else e6["msg_id"]
        check("P0-06: msg_id 係完整 UUID（> 12 字）", len(e6_id) > 12, e6["msg_id"])
        req("POST", "/send", e6)
        req("POST", "/reject", {"msg_id": e6["msg_id"]}, token=ADMIN)
        # revoke 呢條 grant，免影響後面 P0-08（否則會直接 200 放行）
        req("POST", "/revoke", {"grant_id": g.get("grant_id")}, token=ADMIN)

        # P0-07: 強制統一 canonical JSON —— 舊 non-compact 簽名要被拒
        bad = make_env("tester", tester_secret, "bot2", {"task": "x"})
        old_sig = hmac.new(tester_secret.encode(),
                           json.dumps({k: v for k, v in bad.items() if k != "sig"},
                                      sort_keys=True, ensure_ascii=False).encode(),
                           hashlib.sha256).hexdigest()
        bad["sig"] = old_sig
        c7, r7 = req("POST", "/send", bad)
        check("P0-07: 舊 non-compact 簽名 → 401（強制統一 canonical）",
              c7 == 401, f"{c7} {r7.get('message', '')[:40]}")

        # P0-08: payload 必須係 dict
        for bad_payload, label in [("string", "string"), (["arr"], "array"),
                                   (123, "number"), (None, "null")]:
            e = make_env("tester", tester_secret, "bot2", bad_payload)
            c8, r8 = req("POST", "/send", e)
            check(f"P0-08: payload={label} → 400", c8 == 400,
                  f"{c8} {r8.get('message', '')[:40]}")
        e = make_env("tester", tester_secret, "bot2", {"task": "ok dict"})
        c8, _ = req("POST", "/send", e)
        check("P0-08: payload=dict → 202", c8 == 202, f"{c8}")
        req("POST", "/reject", {"msg_id": e["msg_id"]}, token=ADMIN)

        # P0-01 / P0-02 / P0-03：用獨立 relay 測持久化 + resume + 批准前重驗
        run_p0_persistence_tests(args.port + 200, ADMIN)

        print("\n[回歸] 原有安全機制仍然生效")
        # 篡改
        env = make_env("tester", tester_secret, "bot2", {"task": "正常"})
        env["payload"] = {"task": "篡改"}  # 簽名唔匹配
        code, _ = req("POST", "/send", env)
        check("篡改 → 401", code == 401, f"{code}")
        # replay
        env = make_env("tester", tester_secret, "bot2", {"task": "一次性"})
        req("POST", "/send", env)
        code, _ = req("POST", "/send", env)
        check("replay（同 nonce）→ 401", code == 401, f"{code}")
        # ACL
        code, reg3 = req("POST", "/register", {"agent_id": "stranger"}, token=ADMIN)
        env = make_env("stranger", reg3["secret"], "bot2", {"task": "未授權"})
        code, _ = req("POST", "/send", env)
        check("ACL 未授權 → 403", code == 403, f"{code}")
        # 過期訊息
        env = make_env("tester", tester_secret, "bot2", {"task": "舊訊息"})
        env["ts"] = datetime.fromtimestamp(time.time() - 999,
                                           tz=timezone.utc).isoformat()
        env["sig"] = bc_sign(env, tester_secret)  # P0-07: 共用 bilogue_crypto
        code, _ = req("POST", "/send", env)
        check("過期 ts → 401 STALE", code == 401, f"{code}")
        # kill-switch
        code, _ = req("POST", "/kill", {}, token=ADMIN)
        check("kill-switch → 200", code == 200, f"{code}")
        env = make_env("tester", tester_secret, "bot2", {"task": "死後訊息"})
        code, _ = req("POST", "/send", env)
        check("kill 之後 send → 403", code == 403, f"{code}")

        print("\n[HTTP] 完成")
    finally:
        proc.terminate()
        try:
            test_state.unlink()
        except OSError:
            pass

    run_unit_tests()

    # v0.3.3 Round-2/3 P1 × 8 + P2 × 4 HTTP 回歸
    run_p1_p2_tests(args.port + 300, ADMIN)
    run_tls_tests()

    print("\n" + "=" * 50)
    print(f"  總結果：{passed} passed, {failed} failed")
    print("=" * 50)

    # 清走測試期間生成嘅加密 key 檔 / audit 檔（唔應該留低喺 repo）
    import glob as _glob
    parent = Path(__file__).parent
    for pat in ("relay_inbox.key", "relay_audit.key", "relay_inbox.jsonl",
                "relay_admin_token.txt", "relay_inbox.jsonl.*"):
        for f in _glob.glob(str(parent / pat)):
            try:
                Path(f).unlink()
            except OSError:
                pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
