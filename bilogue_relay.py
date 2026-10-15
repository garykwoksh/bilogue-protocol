#!/usr/bin/env python3
"""
bilogue_relay.py — Bilogue HTTP Relay Server (Route A) v0.3.3
=============================================================
企喺中間嘅 HTTP relay：Agent A POST envelope → relay 驗簽名 + nonce + ACL
→ 彈 Consent Gate → 批准先送去 Agent B → 回覆寫返 inbox。

v0.2 安全升級：
  P0-1: /inbox/{agent_id} 加 Bearer Token 認證（agent secret）
  P0-2: Consent Gate 喺 relay 版真正攔截（非 auto-approve 返回 202 PENDING）
  P0-3: nonce 去重 + ts 時間窗口驗證（防重放攻擊）
  P0-4: /kill /register /allow /approve /reject 加 admin token 認證

v0.2.1 安全修補（對應外部安全審計，全部經 PoC 驗證）：
  SEC-01 [高危] 重複註冊唔再回傳現有 agent 嘅 secret（返回 409）
  SEC-02 [高危] Consent Gate 拒絕重複 msg_id（防 pending 訊息被掉包）
  SEC-03 [中危] Request body 設 1MB 上限（防記憶體 DoS），Content-Length 安全解析
  SEC-04 [中危] query string 用 parse_qs 正規解析，畸形參數返回 400 唔再炸 handler
  SEC-05 [低危] /acl 改為 admin-only；/health 精簡到只返 status
  SEC-06 [中危] admin token 改用 hmac.compare_digest（防 timing attack）
  SEC-07 [中危] nonce cache 同 pending queue 加上限 + TTL（防無界增長）
  SEC-08 [中危] 改用 ThreadingHTTPServer + 全域鎖（防單線程阻塞 + race condition）
  SEC-09 [低危] 簽名 secret 同 inbox 讀取 token 分離（職責分離）
  SEC-10 [低危] inbox 讀取後即清除已讀訊息（fix 「未讀」語意 + 内存積壓）
  SEC-11 [低危] admin token 唔再明文打印；自動生成時寫入 0600 權限檔案
  SEC-12 [資訊] /inbox 對未知 agent 同錯 token 一律返回 403（防 agent 枚舉）
  SEC-13 [中危] handler 全域 try/except，未捕捉異常返回 500 唔再 cut 連線
  SEC-14 [高危] 待批准/被拒訊息唔再落入收件隊列（修復 Consent Gate 經 inbox 繞過）

v0.3 功能升級 —— Consent 三級政策（解決「逐條批准 → 溝通唔暢」嘅矛盾）：
  L1 逐條訊息批准（預設，同 v0.2 一樣）
  L2 對話鏈同意：approve 一條 DELEGATE 時 scope=conversation（預設），
     佢嘅後續往來（in_reply_to 鏈、同一對 agent）自動放行，上限 CONV_MAX_MSGS 條
  L3 限時信任窗口：POST /grant 批准一對 agent 喺限期 + 訊息預算內自由通訊，
     隨時 POST /revoke 撤銷；GET /grants 睇活躍窗口
  所有放行 / 撤銷照落 audit log；kill-switch 一刀切照舊

v0.3.1 安全修補（第二輪外部審計）：
  SEC-15 [中危] conversations 對話鏈加 TTL（預設 1h，BILOGUE_CONV_TTL）+ 總量上限
  SEC-16 [中危] 每連線 request timeout（30s）+ 線程槽上限（64），防 slow-loris
  SEC-17 [低危] approve 預設 scope=once（最小權限），開對話鏈要明確寫 conversation
  SEC-18 [低危] L3 信任窗口總數上限 1000
  SEC-19 [低危] audit log 按大小 rotation（預設 10MB x 3 舊檔，BILOGUE_MAX_LOG_BYTES）
  SEC-20 [資訊] 強制執行 Intent 狀態機：回覆要帶有效 in_reply_to + 合法轉移

v0.3.2 Round-1 P0 安全修正（第三輪外部審計，8 項 P0）：
  P0-01 [高]   Relay 預設只綁 127.0.0.1；非 loopback 顯眼警告（LAN/Internet 要用 HTTPS）
  P0-02 [高]   Kill-switch 持久化（relay_state.json）：restart 仍 STOPPED；kill 撤銷 grants；
              新增 POST /resume（admin）恢復，唔會令舊 grant 自動復活
  P0-03 [高]   批准前重新驗證（kill / 雙方註冊 / ACL / 簽名 / freshness / pending TTL）
  P0-04 [高]   批准綁定不可變 envelope hash；產獨立 consent_id
  P0-05 [高]   Inbox 由 read-and-delete 改為 delivery + ACK（POST /messages/{aid}/{mid}/ack）
  P0-06 [中]   所有截短 UUID（grant_id 等）改完整 128-bit UUID
  P0-07 [中]   共用 bilogue_crypto.py 統一 canonical JSON 簽名（separators=(",",":")）
  P0-08 [中]   payload 必須係 JSON object（唔接受 scalar / array / null）

v0.3.3 Round-2/3（P1 × 8 + P2 × 4）安全修正（第四輪外部審計殘餘項）：
  P1-01 [中]   非 loopback 綁定強制 TLS；否則拒絕啟動（除非 --allow-insecure-lan 顯式覆寫）
  P1-02 [中]   admin token 輪換（POST /rotate-token）；滑動窗口速率限制（global / send / admin）
  P1-03 [中]   inbox/state 磁碟加密（Fernet，cryptography 可用時；唔可用明文 + 警告）
  P1-04 [中]   客戶端錯誤處理 / 重試語意改善（bilogue_send.py）
  P1-05 [中]   消息級 TTL（可配置 BILOGUE_MSG_TTL）+ 全局速率限制防 DoS
  P1-06 [中]   grant 撤銷即時推送 system 通知去 receiver inbox
  P1-07 [中]   防篡改審計日誌：HMAC 鏈（prev → hash），GET /audit/verify 可驗證
  P1-08 [中]   健康檢查 GET /healthz + metrics GET /metrics
  P2-01 [低]   nonce 重用檢測窗口延長到 1h（NONCE_REPLAY_TTL）+ LRU 淘汰
  P2-02 [低]   對外錯誤泛型化（500 唔再洩漏異常類名）
  P2-03 [低]   集中配置 CONFIG + validate_config() 啟動校驗
  P2-04 [資訊] 模糊測試套件 fuzz_relay.py

跑法：
  # 啟動 relay（預設 port 8420，自動生成 admin token 並寫入 relay_admin_token.txt）
  python3 bilogue_relay.py --port 8420

  # 自動批准模式（測試用，跳過 Consent Gate）
  python3 bilogue_relay.py --port 8420 --auto-approve

  # 指定 admin token
  python3 bilogue_relay.py --port 8420 --admin-token my-secret-admin

API 端點：
  POST /send          — 提交一個 intent envelope（需簽名 + nonce + ts）
  GET  /inbox/{aid}   — 拎某個 agent 嘅未 ACK 訊息（需 Bearer: agent read_token）
  POST /messages/{aid}/{mid}/ack — ACK 一條 inbox 訊息（需 Bearer: agent read_token）
  POST /register      — 註冊新 agent（需 Bearer: admin token；重複註冊返回 409）
  GET  /acl           — 睇 ACL 授權表（需 Bearer: admin token）
  GET  /health        — 健康檢查（公開，只返 status）
  POST /kill          — kill-switch（需 Bearer: admin token）
  GET  /pending       — 列出待批准訊息（需 Bearer: admin token）
  POST /approve       — 批准待批准訊息（需 Bearer: admin token；v0.3 支援 scope=once/conversation）
  POST /reject        — 拒絕待批准訊息（需 Bearer: admin token）
  POST /grant         — v0.3 L3：建立限時信任窗口（需 Bearer: admin token）
  POST /revoke        — v0.3：撤銷信任窗口（需 Bearer: admin token）
  GET  /grants        — v0.3：列出活躍信任窗口（需 Bearer: admin token）
"""

import argparse
import hashlib
from collections import deque
import hmac
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import ssl as _ssl
import secrets
import base64

# P0-07: 共用 canonical JSON + HMAC 簽名模組
from bilogue_crypto import canonical_json, sign as crypto_sign, \
    verify as crypto_verify, envelope_hash

# P1-03: 磁碟加密（優雅降級）—— cryptography 可用就用 Fernet，否則明文 + 警告
try:
    from cryptography.fernet import Fernet
    _FERNET_AVAILABLE = True
except Exception:  # pragma: no cover
    Fernet = None
    _FERNET_AVAILABLE = False

# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------

INTENT_TYPES = {"QUERY", "DELEGATE", "PROPOSE", "ACCEPT", "REJECT", "REPORT", "PING"}

INBOX_PATH = Path(__file__).parent / "relay_inbox.jsonl"

MAX_AGE_SECONDS = 300          # 訊息時間窗口：5 分鐘
MAX_BODY_BYTES = 1 * 1024 * 1024   # SEC-03: request body 上限 1MB
MAX_PENDING = 1000             # SEC-07: pending queue 上限
PENDING_TTL_SECONDS = 600      # SEC-07: pending 訊息 10 分鐘未處理即過期
NONCE_CACHE_MAX = 100_000      # SEC-07: nonce cache 上限

# v0.3: Consent 三級政策預設值
GRANT_DEFAULT_TTL = 1800       # L3 限時窗口預設 30 分鐘
GRANT_MAX_TTL = 24 * 3600      # L3 窗口上限 24 小時
GRANT_DEFAULT_MAX_MSGS = 100   # L3 窗口訊息數預算預設值
CONV_MAX_MSGS = 50             # L2 單一對話鏈訊息數上限

# v0.3.1 安全修補（SEC-15~20）
CONV_TTL_SECONDS = int(os.environ.get("BILOGUE_CONV_TTL", 3600))  # SEC-15: 對話鏈 TTL
CONV_MAX_ACTIVE = 1000         # SEC-15: 同時活躍對話鏈上限
MAX_GRANTS = 1000              # SEC-18: L3 信任窗口總數上限
MAX_LOG_BYTES = int(os.environ.get("BILOGUE_MAX_LOG_BYTES", 10 * 1024 * 1024))  # SEC-19
LOG_BACKUPS = 3                # SEC-19: audit log 保留舊檔數
REQUEST_TIMEOUT_SECONDS = 30   # SEC-16: 每個連線嘅 request timeout
MAX_WORKER_THREADS = 64        # SEC-16: 最大並發處理線程
MSG_INDEX_MAX = 10_000         # SEC-20: 狀態機用嘅已送達訊息索引上限

# P0-02: kill-switch 持久化狀態檔（預設放 relay 同目錄，可用 --state-file 覆寫）
STATE_FILE = Path(__file__).parent / "relay_state.json"
# P0-05: Inbox ACK —— 送達後等 receiver ACK，ACK 之前可安全重取（crash 唔會漏訊息）
ACK_DEADLINE_SECONDS = 300     # 送達後 300s 內要 ACK；過咗只係繼續 redeliver（at-least-once）

# P1-03: 磁碟加密 key（Fernet，0600）；P1-07: audit HMAC 鏈 key（持久化，獨立）
CRYPTO_KEY_FILE = Path(__file__).parent / "relay_inbox.key"
AUDIT_KEY_FILE = Path(__file__).parent / "relay_audit.key"
RELAY_VERSION = "0.3.3"

# SEC-20: Intent 狀態機（同 SPEC.md 一致）
INTENT_TRANSITIONS = {
    "QUERY":    {"REPORT", "ACCEPT", "REJECT"},
    "DELEGATE": {"PROPOSE", "ACCEPT", "REJECT", "REPORT"},
    "PROPOSE":  {"ACCEPT", "REJECT"},
    "ACCEPT":   {"REPORT"},
    "REJECT":   {"QUERY", "DELEGATE"},
    "REPORT":   {"QUERY", "DELEGATE"},
    "PING":     {"REPORT"},
}
CONVERSATION_STARTERS = {"QUERY", "DELEGATE", "PING"}

# ===========================================================================
# P2-03: 集中配置（所有安全相關 tunables 一處管理，啟動時校驗）
#   現有散落常數仍保留向後兼容；以下 CONFIG 係「單一可信來源」並做範圍校驗。
# ===========================================================================
CONFIG = {
    # --- 消息生命週期 ---
    "MAX_AGE_SECONDS":  MAX_AGE_SECONDS,                       # SEC-03 時間窗口
    "MSG_TTL_SECONDS":  int(os.environ.get("BILOGUE_MSG_TTL",
                                           MAX_AGE_SECONDS)),   # P1-05: 消息級 TTL（可 > 窗口）
    "PENDING_TTL_SECONDS": PENDING_TTL_SECONDS,                # SEC-07 pending 過期
    "ACK_DEADLINE_SECONDS": ACK_DEADLINE_SECONDS,              # P0-05 ACK 期限

    # --- 重放防護 ---
    "NONCE_REPLAY_TTL": int(os.environ.get("BILOGUE_NONCE_TTL",
                                           3600)),              # P2-01: nonce 重用檢測窗口（延長到 1h）
    "NONCE_CACHE_MAX":  NONCE_CACHE_MAX,

    # --- L2 / L3 信任政策 ---
    "CONV_TTL_SECONDS":  CONV_TTL_SECONDS,
    "CONV_MAX_MSGS":     CONV_MAX_MSGS,
    "CONV_MAX_ACTIVE":   CONV_MAX_ACTIVE,
    "GRANT_DEFAULT_TTL": GRANT_DEFAULT_TTL,
    "GRANT_MAX_TTL":     GRANT_MAX_TTL,
    "MAX_GRANTS":        MAX_GRANTS,

    # --- DoS / 速率限制（P1-02 + P1-05）---
    "GLOBAL_RATE_MAX":   int(os.environ.get("BILOGUE_GLOBAL_RATE", 200)),   # 每窗口全局請求數
    "GLOBAL_RATE_WINDOW": int(os.environ.get("BILOGUE_RATE_WINDOW", 60)),   # 秒
    "SEND_RATE_MAX":     int(os.environ.get("BILOGUE_SEND_RATE", 50)),      # 每 sender 每窗口
    "ADMIN_RATE_MAX":    int(os.environ.get("BILOGUE_ADMIN_RATE", 30)),     # 每 admin IP 每窗口

    # --- 運行期 ---
    "MAX_BODY_BYTES":    MAX_BODY_BYTES,
    "MAX_PENDING":       MAX_PENDING,
    "MAX_WORKER_THREADS": MAX_WORKER_THREADS,
    "REQUEST_TIMEOUT_SECONDS": REQUEST_TIMEOUT_SECONDS,
    "MAX_LOG_BYTES":     MAX_LOG_BYTES,
    "LOG_BACKUPS":       LOG_BACKUPS,
}


def validate_config(cfg=None):
    """P2-03: 校驗所有配置項在合理範圍。非法拋 ValueError（fail-closed）。"""
    cfg = cfg or CONFIG
    errors = []
    pos = ("MSG_TTL_SECONDS", "PENDING_TTL_SECONDS", "ACK_DEADLINE_SECONDS",
           "NONCE_REPLAY_TTL", "CONV_TTL_SECONDS", "GRANT_DEFAULT_TTL",
           "GRANT_MAX_TTL", "CONV_MAX_MSGS", "CONV_MAX_ACTIVE", "MAX_GRANTS",
           "NONCE_CACHE_MAX", "MAX_BODY_BYTES", "MAX_PENDING",
           "MAX_WORKER_THREADS", "MAX_LOG_BYTES", "LOG_BACKUPS")
    for k in pos:
        v = cfg.get(k)
        if not isinstance(v, int) or v <= 0:
            errors.append(f"{k} 必須係正整數（現值={v!r}）")
    for k in ("GLOBAL_RATE_MAX", "GLOBAL_RATE_WINDOW", "SEND_RATE_MAX",
              "ADMIN_RATE_MAX"):
        v = cfg.get(k)
        if not isinstance(v, int) or v <= 0:
            errors.append(f"{k} 必須係正整數（現值={v!r}）")
    if cfg.get("GRANT_DEFAULT_TTL", 0) > cfg.get("GRANT_MAX_TTL", 0):
        errors.append("GRANT_DEFAULT_TTL 唔可以大過 GRANT_MAX_TTL")
    if cfg.get("MSG_TTL_SECONDS", 0) < cfg.get("MAX_AGE_SECONDS", 0):
        errors.append("MSG_TTL_SECONDS 唔可以細過 MAX_AGE_SECONDS")
    if errors:
        raise ValueError("配置校驗失敗：\n  - " + "\n  - ".join(errors))
    return True


# P1-02 / P1-05: 滑動窗口速率限制器（in-memory，線程安全）
class RateLimiter:
    """滑動窗口計數器：key -> deque(timestamps)。超過上限返回 False。"""

    def __init__(self, max_requests, window_seconds):
        self.max = max_requests
        self.window = window_seconds
        self.buckets = {}
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        with self.lock:
            dq = self.buckets.get(key)
            if dq is None:
                dq = deque()
                self.buckets[key] = dq
            # 清走窗口外的舊戳
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.max:
                return False
            dq.append(now)
            return True

    def count(self):
        with self.lock:
            return sum(len(d) for d in self.buckets.values())


# ===========================================================================
# P1-03: 磁碟加密 Store（優雅降級）
#   若 cryptography 可用：用 Fernet 加密每行 audit / state。key 由隨機生成、
#   存於 relay_inbox.key（0600，gitignore），唔依賴 admin token（避免輪換斷鏈）。
#   不可用：明文 + 啟動警告（仍可用，但係 residual risk）。
# ===========================================================================
class CryptoStore:
    def __init__(self, key_file, enabled=None):
        self.key_file = Path(key_file)
        self.enabled = _FERNET_AVAILABLE if enabled is None else enabled
        self.fernet = None
        self._warned = False
        if self.enabled:
            self._init_key()

    def _init_key(self):
        try:
            if self.key_file.exists():
                key = self.key_file.read_text(encoding="utf-8").strip()
            else:
                key = Fernet.generate_key().decode()
                self.key_file.write_text(key, encoding="utf-8")
                try:
                    os.chmod(self.key_file, 0o600)
                except OSError:
                    pass
            self.fernet = Fernet(key.encode())
        except Exception:  # pragma: no cover
            self.enabled = False
            self.fernet = None

    def encrypt_line(self, text):
        if not self.fernet:
            if not self._warned:
                print("  ⚠️  [P1-03] cryptography 唔可用 / key 初始化失敗："
                      "audit/state 以明文寫入磁碟（敏感資料暴露風險）。")
                self._warned = True
            return text
        try:
            return "F:" + self.fernet.encrypt(text.encode()).decode()
        except Exception:  # pragma: no cover
            return text

    def decrypt_line(self, text):
        if text.startswith("F:"):
            if not self.fernet:
                raise ValueError("加密行但 Fernet 唔可用，無法解密")
            return self.fernet.decrypt(text[2:].encode()).decode()
        return text

    @property
    def using_encryption(self):
        return self.fernet is not None


class AgentRegistry:
    def __init__(self):
        self.agents = {}
        self.acl = {}
        self.seen_nonces = {}    # SEC-07: nonce -> first_seen_epoch（有 TTL 唔再無界增長）
        self.lock = threading.Lock()  # SEC-08: ThreadingHTTPServer 下嘅 race 防護

    def register(self, agent_id, display_name=None, secret=None, read_token=None):
        """註冊 agent。返回 (info, created)。已存在則 created=False 且唔會洩漏 secret。"""
        with self.lock:
            if agent_id in self.agents:
                # SEC-01: 唔再回傳現有記錄，由調用方決定點拒絕
                return None, False
            if secret is None:
                secret = hashlib.sha256(
                    f"{agent_id}:{time.time()}:{uuid.uuid4()}".encode()
                ).hexdigest()[:32]
            if read_token is None:
                # SEC-09: inbox 讀取 token 同簽名 secret 分離
                read_token = hashlib.sha256(
                    f"read:{agent_id}:{time.time()}:{uuid.uuid4()}".encode()
                ).hexdigest()[:32]
            self.agents[agent_id] = {
                "secret": secret,
                "read_token": read_token,
                "display_name": display_name or agent_id,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }
            self.acl[agent_id] = set()
            return self.agents[agent_id], True

    def allow(self, a, b):
        with self.lock:
            if a not in self.agents or b not in self.agents:
                return False
            self.acl.setdefault(a, set()).add(b)
            self.acl.setdefault(b, set()).add(a)
            return True

    def check_acl(self, sender, receiver):
        with self.lock:
            return receiver in self.acl.get(sender, set())

    def get_agent(self, agent_id):
        with self.lock:
            return self.agents.get(agent_id)

    def sign(self, agent_id, payload):
        """DEPRECATED (P0-07): 使用 bilogue_crypto.sign() 代替。"""
        secret = self.agents[agent_id]["secret"]
        return crypto_sign({"_payload": payload}, secret)

    def verify(self, agent_id, payload, signature):
        """DEPRECATED (P0-07): 使用 bilogue_crypto.verify() 代替。
        保留向後兼容：接受 (agent_id, body_str, sig) 格式。"""
        agent = self.get_agent(agent_id)
        if agent is None:
            return False
        expected = hmac.new(agent["secret"].encode(), payload.encode(),
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def check_nonce(self, nonce):
        """SEC-07 + P2-01: nonce 去重 + TTL 清理 + 容量上限。
        P2-01: 重用檢測窗口由 MAX_AGE_SECONDS 延長到 NONCE_REPLAY_TTL（默認 1h），
               且容量滿時按最舊 LRU 淘汰（唔係只清過期），真正防重放。
        未見過則記錄並返回 True。"""
        now = time.time()
        replay_ttl = CONFIG["NONCE_REPLAY_TTL"]
        with self.lock:
            # 清走已過重用窗口嘅 nonce
            expired = [n for n, t in self.seen_nonces.items()
                       if now - t > replay_ttl]
            for n in expired:
                del self.seen_nonces[n]
            if nonce in self.seen_nonces:
                return False
            if len(self.seen_nonces) >= NONCE_CACHE_MAX:
                # 滿咗就逐最舊嘅 10%（LRU），確保長期重放都擋到
                oldest = sorted(self.seen_nonces.items(), key=lambda kv: kv[1])
                for n, _ in oldest[: NONCE_CACHE_MAX // 10]:
                    del self.seen_nonces[n]
            self.seen_nonces[nonce] = now
            return True


class RelayBus:
    """Thread-safe JSONL inbox + ACK-aware in-memory queue per agent.
    P0-05: 送達後標 DELIVERED_NOT_ACK，receiver ACK 後先 ACKNOWLEDGED。
           ACK 之前可安全重取（at-least-once），client crash 唔會漏訊息。
    P1-03: 寫入磁碟時經 CryptoStore 加密（Fernet，可用時）。
    P1-07: 每條 audit 記錄掛 HMAC 鏈（prev_hash → hash），篡改可檢測。
    """

    def __init__(self, path, crypto_store=None, audit_key=None):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.lock = threading.Lock()
        self.crypto = crypto_store
        self.audit_key = (audit_key or secrets.token_hex(32)).encode()
        # agent_id -> [{"env", "ack_state", "attempts", "delivered_at"}]
        self.queues = {}
        # P1-07: HMAC 鏈上一個 hash（跨重啟由檔案最後一行續接）
        self.last_log_hash = self._load_last_hash()

    def _load_last_hash(self):
        """P1-07: 由現有 audit 檔最後一行續接 HMAC 鏈（唔使每次讀全檔）。"""
        try:
            size = self.path.stat().st_size
            if size == 0:
                return "0" * 64
            with open(self.path, "rb") as f:
                f.seek(max(0, size - 4096))
                chunk = f.read().decode("utf-8", "replace")
            lines = [l for l in chunk.splitlines() if l.strip()]
            if not lines:
                return "0" * 64
            last = lines[-1]
            if self.crypto:
                last = self.crypto.decrypt_line(last)
            entry = json.loads(last)
            return entry.get("_audit_hash", "0" * 64)
        except (OSError, json.JSONDecodeError, ValueError):
            return "0" * 64

    def append(self, envelope, deliver=True):
        """寫入 audit log；deliver=True 先會放入 receiver 嘅 inbox queue（待 ACK）。
        SEC-14: 審計記錄（REJECTED / PENDING_APPROVAL 等）唔准落入收件隊列，
        否則 Consent Gate 未批准嘅訊息會喺 inbox 提前洩漏。
        P1-07: 加 _audit_prev / _audit_hash HMAC 鏈；P1-03: 加密後寫入。
        """
        envelope["delivery_ts"] = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self._writes = getattr(self, "_writes", 0) + 1
            if self._writes % 100 == 1:
                self._rotate_if_needed()  # SEC-19
            # P1-07: 鏈接上一條
            prev = self.last_log_hash
            envelope["_audit_prev"] = prev
            chain_input = canonical_json({k: v for k, v in envelope.items()
                                         if k not in ("sig", "delivery",
                                                      "delivery_ts",
                                                      "_audit_prev",
                                                      "_audit_hash")})
            h = hmac.new(self.audit_key,
                         (prev + "|" + chain_input).encode(),
                         hashlib.sha256).hexdigest()
            envelope["_audit_hash"] = h
            self.last_log_hash = h
            line = json.dumps(envelope, ensure_ascii=False)
            if self.crypto:
                line = self.crypto.encrypt_line(line)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            receiver = envelope.get("receiver")
            if receiver and deliver:
                self.queues.setdefault(receiver, []).append({
                    "env": envelope,
                    "ack_state": "DELIVERED_NOT_ACK",
                    "attempts": 0,
                    "delivered_at": time.time(),
                })

    def _rotate_if_needed(self):
        """SEC-19: audit log 按大小 rotation（.1/.2/.3），防單檔填滿磁碟。"""
        try:
            if self.path.stat().st_size < MAX_LOG_BYTES:
                return
        except OSError:
            return
        for i in range(LOG_BACKUPS - 1, 0, -1):
            src = self.path.with_name(f"{self.path.name}.{i}")
            dst = self.path.with_name(f"{self.path.name}.{i + 1}")
            if src.exists():
                src.replace(dst)
        self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def verify_audit_log(self):
        """P1-07: 重算 HMAC 鏈，返回 (ok, first_bad_line)。"""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return True, -1  # 無檔 = 無可篡改
        prev = "0" * 64
        for i, raw in enumerate(lines):
            if not raw.strip():
                continue
            try:
                line = self.crypto.decrypt_line(raw) if self.crypto else raw
                entry = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                return False, i
            if entry.get("_audit_prev") != prev:
                return False, i
            chain_input = canonical_json({k: v for k, v in entry.items()
                                         if k not in ("sig", "delivery",
                                                      "delivery_ts",
                                                      "_audit_prev",
                                                      "_audit_hash")})
            expect = hmac.new(self.audit_key,
                              (prev + "|" + chain_input).encode(),
                              hashlib.sha256).hexdigest()
            if expect != entry.get("_audit_hash"):
                return False, i
            prev = entry.get("_audit_hash", prev)
        return True, -1

    def fetch_inbox(self, agent_id):
        """P0-05: 拎未 ACK 嘅訊息（唔會即刪）。每次 fetch 計一次 delivery attempt。"""
        with self.lock:
            out = []
            for it in self.queues.get(agent_id, []):
                if it["ack_state"] == "DELIVERED_NOT_ACK":
                    it["attempts"] += 1
                    it["delivered_at"] = time.time()
                    out.append(it["env"])
            return out

    def ack_message(self, agent_id, msg_id):
        """P0-05: receiver ACK 一條訊息。成功返回 True，否则 False。"""
        with self.lock:
            for it in self.queues.get(agent_id, []):
                if it["env"].get("msg_id") == msg_id and \
                        it["ack_state"] == "DELIVERED_NOT_ACK":
                    it["ack_state"] = "ACKNOWLEDGED"
                    return True
            return False


# ---------------------------------------------------------------------------
# Relay Server
# ---------------------------------------------------------------------------

class BilogueRelay:
    """Relay 邏輯：驗簽名 → nonce → ACL → Consent Gate → 轉發。"""

    def __init__(self, auto_approve=False, admin_token=None, state_file=None,
                 crypto_store=None, audit_key=None, inbox_path=None):
        self.registry = AgentRegistry()
        self.bus = RelayBus(inbox_path or INBOX_PATH, crypto_store=crypto_store,
                            audit_key=audit_key)
        self.auto_approve = auto_approve
        self.state_file = state_file  # P0-02: None = 唔持久化（例如單元測試）
        self.crypto = crypto_store
        # P1-02 / P1-05: 速率限制器
        self.rate_global = RateLimiter(CONFIG["GLOBAL_RATE_MAX"],
                                       CONFIG["GLOBAL_RATE_WINDOW"])
        self.rate_send = RateLimiter(CONFIG["SEND_RATE_MAX"],
                                    CONFIG["GLOBAL_RATE_WINDOW"])
        self.rate_admin = RateLimiter(CONFIG["ADMIN_RATE_MAX"],
                                     CONFIG["GLOBAL_RATE_WINDOW"])
        self.rate_limited_total = 0
        # P0-02: restart 後仍維持 STOPPED（除非 admin resume）
        self.killed = self._load_killed_state()
        self.admin_token = admin_token or hashlib.sha256(
            f"admin:{time.time()}:{uuid.uuid4()}".encode()
        ).hexdigest()[:32]
        # P0-04: pending 儲 envelope + 入 queue 時間 + 不可變 envelope hash
        self.pending_approvals = {}  # msg_id -> {"envelope","received","hash"}
        self.pending_lock = threading.Lock()  # SEC-08

        # v0.3: Consent 三級政策狀態
        # L3 限時信任窗口：(sender, receiver) -> {"grant_id", "expires", "remaining"}
        self.pair_grants = {}
        # L2 對話鏈同意：root_msg_id -> {"pair": frozenset, "msg_ids": set, "remaining"}
        self.conversations = {}
        self.consent_lock = threading.Lock()
        # SEC-20: 已送達訊息索引（狀態機用）：msg_id -> {"intent", "pair"}
        self.msg_index = {}
        self.msg_index_order = deque()

        # 預設兩個 demo agent
        self.registry.register("karina", "Karina (分析助手)")
        self.registry.register("stfund", "St.Fund (核數助手)")
        self.registry.allow("karina", "stfund")

    # P0-02: kill-switch 持久化
    def _load_killed_state(self):
        if not self.state_file:
            return False
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return bool(data.get("killed", False))
        except (OSError, json.JSONDecodeError):
            return False

    def _save_state(self):
        if not self.state_file:
            return
        try:
            tmp = self.state_file.with_name(self.state_file.name + ".tmp")
            tmp.write_text(json.dumps(
                {"killed": self.killed,
                 "saved_at": datetime.now(timezone.utc).isoformat()},
                ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.state_file)
        except OSError:
            pass

    def _verify_sig(self, envelope):
        """驗證 HMAC 簽名。返回 (ok, reason)。
        P0-07: 使用 bilogue_crypto.verify 統一 canonical JSON。"""
        sig = envelope.get("sig")
        if not sig:
            return False, "缺 sig 簽名"

        sender = envelope.get("sender")
        agent = self.registry.get_agent(sender)
        if agent is None:
            return False, "簽名無效（sender 未註冊）"

        if crypto_verify(envelope, agent["secret"], sig):
            return True, "OK"
        return False, "簽名無效（可能被篡改）"

    def _check_freshness(self, envelope):
        """檢查時間戳新鮮度。返回 (ok, reason)。"""
        ts_str = envelope.get("ts")
        if not ts_str:
            return False, "缺 ts 時間戳"
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            return False, "時間戳格式無效"
        age = abs((datetime.now(timezone.utc) - ts).total_seconds())
        msg_ttl = CONFIG["MSG_TTL_SECONDS"]  # P1-05: 可配置消息級 TTL
        if age > msg_ttl:
            return False, f"訊息過期（{int(age)}秒前，上限{msg_ttl}秒）"
        return True, "OK"

    def _expire_pending(self):
        """SEC-07: 清走過期 pending。"""
        now = time.time()
        with self.pending_lock:
            expired = [m for m, e in self.pending_approvals.items()
                       if now - e["received"] > PENDING_TTL_SECONDS]
            for m in expired:
                env = self.pending_approvals.pop(m)["envelope"]
                self.bus.append({**env, "delivery": "EXPIRED_PENDING"},
                                deliver=False)

    # ------------------------------------------------------------------
    # v0.3: Consent 三級政策
    #   L1 逐條訊息批准（預設，最嚴）
    #   L2 對話鏈同意：批准咗一個 DELEGATE，佢嘅後續 PROPOSE/ACCEPT/REPORT
    #      （經 in_reply_to 鏈、同一對 agent）自動放行
    #   L3 限時信任窗口：admin 批准一對 agent 喺限期 + 訊息預算內自由通訊
    # ------------------------------------------------------------------

    def _check_pair_grant(self, sender, receiver):
        """L3: 檢查限時信任窗口。返回 True 並扣預算，否則 False。"""
        now = time.time()
        key = (sender, receiver)
        with self.consent_lock:
            grant = self.pair_grants.get(key)
            if grant is None:
                return False
            if now >= grant["expires"]:
                del self.pair_grants[key]
                return False
            if grant["remaining"] <= 0:
                return False
            grant["remaining"] -= 1
            return True

    def _check_conversation(self, envelope):
        """L2: 檢查對話鏈同意。in_reply_to 指向已批准鏈 + 同一對 agent 即放行。
        放行時將今次 msg_id 接入條鏈，等下一棒都可以行。"""
        in_reply_to = envelope.get("in_reply_to")
        if not in_reply_to:
            return False
        pair = frozenset({envelope.get("sender"), envelope.get("receiver")})
        now = time.time()
        with self.consent_lock:
            # SEC-15: 惰性清理過期對話鏈，防無界增長 + O(n) 放大
            expired = [k for k, c in self.conversations.items()
                       if now - c["created"] > CONV_TTL_SECONDS]
            for k in expired:
                del self.conversations[k]
            for conv in self.conversations.values():
                if conv["pair"] == pair and in_reply_to in conv["msg_ids"]:
                    if conv["remaining"] <= 0:
                        return False
                    conv["remaining"] -= 1
                    msg_id = envelope.get("msg_id")
                    if msg_id:
                        conv["msg_ids"].add(msg_id)
                    return True
        return False

    def _adopt_into_conversation(self, envelope, scope):
        """approve 時調用：scope=conversation 就開一條對話鏈。"""
        if scope != "conversation":
            return
        msg_id = envelope.get("msg_id")
        if not msg_id:
            return
        with self.consent_lock:
            # SEC-15: 活躍對話鏈總量上限，滿咗逐最舊
            if len(self.conversations) >= CONV_MAX_ACTIVE:
                oldest = min(self.conversations.items(),
                             key=lambda kv: kv[1]["created"])[0]
                del self.conversations[oldest]
            self.conversations[msg_id] = {
                "pair": frozenset({envelope.get("sender"),
                                   envelope.get("receiver")}),
                "msg_ids": {msg_id},
                "remaining": CONV_MAX_MSGS,
                "created": time.time(),
            }

    def handle_grant(self, body):
        """L3: 建立限時信任窗口（admin）。"""
        agent_a = body.get("agent_a")
        agent_b = body.get("agent_b")
        direction = body.get("direction", "both")  # both | a_to_b | b_to_a
        try:
            ttl = int(body.get("ttl_seconds", GRANT_DEFAULT_TTL))
            max_msgs = int(body.get("max_messages", GRANT_DEFAULT_MAX_MSGS))
        except (ValueError, TypeError):
            return 400, "BAD_REQUEST: ttl_seconds / max_messages 要係整數", None
        if not agent_a or not agent_b:
            return 400, "BAD_REQUEST: 缺 agent_a 或 agent_b", None
        if self.registry.get_agent(agent_a) is None or \
                self.registry.get_agent(agent_b) is None:
            return 404, "NOT_FOUND: agent 未註冊", None
        if direction not in ("both", "a_to_b", "b_to_a"):
            return 400, "BAD_REQUEST: direction 要係 both / a_to_b / b_to_a", None
        if ttl <= 0 or ttl > GRANT_MAX_TTL:
            return 400, f"BAD_REQUEST: ttl 上限 {GRANT_MAX_TTL} 秒", None
        if max_msgs <= 0:
            return 400, "BAD_REQUEST: max_messages 要大過 0", None

        with self.consent_lock:
            if len(self.pair_grants) >= MAX_GRANTS:
                return 429, f"TOO_MANY_GRANTS: 上限 {MAX_GRANTS}，請先 revoke", None
        grant_id = f"grant-{uuid.uuid4().hex}"  # P0-06: full 128-bit UUID
        expires = time.time() + ttl
        keys = []
        if direction in ("both", "a_to_b"):
            keys.append((agent_a, agent_b))
        if direction in ("both", "b_to_a"):
            keys.append((agent_b, agent_a))
        with self.consent_lock:
            for k in keys:
                self.pair_grants[k] = {"grant_id": grant_id, "expires": expires,
                                       "remaining": max_msgs}
        self.bus.append({"event": "GRANT_CREATED", "grant_id": grant_id,
                         "agents": [agent_a, agent_b], "direction": direction,
                         "ttl_seconds": ttl, "max_messages": max_msgs},
                        deliver=False)
        print(f"  [GRANT] {agent_a} ↔ {agent_b}  direction={direction}  "
              f"ttl={ttl}s  max={max_msgs}  id={grant_id}")
        return 200, "OK", {"grant_id": grant_id, "expires_in": ttl,
                           "max_messages": max_msgs, "direction": direction}

    def handle_revoke(self, body):
        """撤銷 L3 grant（by grant_id 或 agent pair）。
        P1-06: 撤銷後即時推送 system 通知去受影響嘅 receiver inbox。"""
        grant_id = body.get("grant_id")
        agent_a, agent_b = body.get("agent_a"), body.get("agent_b")
        if not grant_id and not (agent_a and agent_b):
            return 400, "BAD_REQUEST: 要 grant_id 或 agent_a + agent_b", None
        removed = 0
        notified = []
        with self.consent_lock:
            for key in list(self.pair_grants.keys()):
                g = self.pair_grants[key]
                if (grant_id and g["grant_id"] == grant_id) or \
                   (agent_a and set(key) == {agent_a, agent_b}):
                    sender, receiver = key
                    del self.pair_grants[key]
                    removed += 1
                    # P1-06: 通知 receiver（key[1]）grant 已被撤銷
                    notified.append(receiver)
        if removed == 0:
            return 404, "NOT_FOUND: 搵唔到對應嘅 grant", None
        # P1-06: 推送 system 訊息去各 receiver inbox（待 ACK）
        for receiver in set(notified):
            sys_env = {
                "msg_id": f"msg-{uuid.uuid4().hex}",
                "sender": "system",
                "receiver": receiver,
                "intent_type": "REPORT",
                "payload": {"type": "grant_revoked",
                            "grant_id": grant_id or f"{agent_a}↔{agent_b}",
                            "note": "L3 信任窗口已被管理員撤銷"},
                "in_reply_to": None,
                "nonce": uuid.uuid4().hex,
                "ts": datetime.now(timezone.utc).isoformat(),
                "sig": "system-notification",
            }
            self.bus.append(sys_env, deliver=True)
        self.bus.append({"event": "GRANT_REVOKED",
                         "grant_id": grant_id or f"{agent_a}↔{agent_b}",
                         "notified_receivers": list(set(notified))},
                        deliver=False)
        return 200, f"REVOKED: 已撤銷 {removed} 條 grant，已通知 {len(set(notified))} 個 receiver", \
               {"removed": removed, "notified": list(set(notified))}

    def handle_grants(self):
        """列出活躍嘅 L3 grant 同 L2 對話鏈數量。"""
        now = time.time()
        items = []
        with self.consent_lock:
            for (a, b), g in list(self.pair_grants.items()):
                if now >= g["expires"]:
                    del self.pair_grants[(a, b)]
                    continue
                items.append({"grant_id": g["grant_id"], "sender": a,
                              "receiver": b,
                              "expires_in": int(g["expires"] - now),
                              "remaining": g["remaining"]})
            conv_count = len(self.conversations)
        return 200, "OK", {"grants": items, "count": len(items),
                           "active_conversations": conv_count}

    def _index_message(self, envelope):
        """SEC-20: 記錄已送達訊息，畀狀態機查。有上限，滿咗逐最舊。"""
        msg_id = envelope.get("msg_id")
        if not msg_id:
            return
        with self.consent_lock:
            if msg_id in self.msg_index:
                return
            while len(self.msg_index) >= MSG_INDEX_MAX and self.msg_index_order:
                old_id = self.msg_index_order.popleft()
                self.msg_index.pop(old_id, None)
            self.msg_index[msg_id] = {
                "intent": envelope.get("intent_type"),
                "pair": frozenset({envelope.get("sender"),
                                   envelope.get("receiver")}),
            }
            self.msg_index_order.append(msg_id)

    def _check_intent_transition(self, envelope):
        """SEC-20: 強制執行 Intent 狀態機。返回 (ok, reason)。
        冇 in_reply_to：只准 CONVERSATION_STARTERS 開新對話。
        有 in_reply_to：父訊息要已送達、同一對 agent、轉移合法。"""
        intent = envelope.get("intent_type")
        in_reply_to = envelope.get("in_reply_to")
        if not in_reply_to:
            if intent not in CONVERSATION_STARTERS:
                return False, (f"{intent} 唔可以開新對話；"
                               f"開新對話要用 QUERY/DELEGATE/PING，"
                               f"否則請帶 in_reply_to")
            return True, "OK"
        with self.consent_lock:
            parent = self.msg_index.get(in_reply_to)
        if parent is None:
            return False, f"in_reply_to={in_reply_to} 搵唔到（未送達、已過期或唔存在）"
        pair = frozenset({envelope.get("sender"), envelope.get("receiver")})
        if parent["pair"] != pair:
            return False, "回覆嘅 agent 組合同原訊息唔同"
        allowed = INTENT_TRANSITIONS.get(parent["intent"], set())
        if intent not in allowed:
            return False, f"狀態機唔准 {parent['intent']} → {intent}"
        return True, "OK"

    def handle_send(self, envelope):
        """處理一個送來嘅 envelope。返回 (status, message, data)。"""
        if self.killed:
            return 403, "RELAY_KILLED: kill-switch 已觸發，所有通信終止", None

        # --- 最小型別門禁（P1-04 加固）---
        # sender / sig 必須係字串，否則 registry 用 unhashable key 查表或
        # compare_digest 比較非字串會拋 TypeError → 500。
        # 呢兩欄係「認證」嘅前提，缺咗維持 401（唔改既有合約），唔係 400。
        for field in ("sender", "sig"):
            if not isinstance(envelope.get(field), str):
                return 401, f"UNAUTHORIZED: 缺或無效 {field}", None

        # --- 驗簽名（先認證，後校驗結構）---
        ok, reason = self._verify_sig(envelope)
        if not ok:
            return 401, f"UNAUTHORIZED: {reason}", None

        # --- 認證通過後嘅結構校驗（畸形欄位 → 400 而唔係 500）---
        for field in ("receiver", "intent_type", "nonce", "ts"):
            v = envelope.get(field)
            if not isinstance(v, str):
                return 400, f"BAD_REQUEST: {field} 必須係字串", None

        receiver = envelope.get("receiver")
        intent = envelope.get("intent_type")

        if intent not in INTENT_TYPES:
            return 400, f"BAD_REQUEST: 未知 intent_type {intent}", None

        payload = envelope.get("payload")
        # P0-08: payload 必須係 JSON object（唔接受 string / number / array / null）
        if not isinstance(payload, dict):
            return 400, ("BAD_REQUEST: payload 必須係 JSON object"
                         "（唔接受 string/number/array/null）"), None

        # --- Replay 防護 ---
        fresh_ok, fresh_reason = self._check_freshness(envelope)
        if not fresh_ok:
            self.bus.append({**envelope, "delivery": f"REJECTED:{fresh_reason}"},
                            deliver=False)
            return 401, f"STALE: {fresh_reason}", None

        nonce = envelope.get("nonce")
        if not nonce:
            return 400, "BAD_REQUEST: 缺 nonce（防重放必填）", None
        if not self.registry.check_nonce(nonce):
            self.bus.append({**envelope, "delivery": "REJECTED:REPLAY"},
                            deliver=False)
            return 401, "REPLAY: nonce 已見過（重放攻擊）", None

        # --- ACL ---
        sender = envelope.get("sender")
        if not self.registry.check_acl(sender, receiver):
            self.bus.append({**envelope, "delivery": "ACL_DENIED"}, deliver=False)
            return 403, f"ACL_DENIED: {sender} 無權聯絡 {receiver}", None

        # --- SEC-20: Intent 狀態機 ---
        sm_ok, sm_reason = self._check_intent_transition(envelope)
        if not sm_ok:
            self.bus.append({**envelope, "delivery": "REJECTED:STATE_MACHINE"},
                            deliver=False)
            return 400, f"BAD_STATE: {sm_reason}", None

        # --- Consent Gate ---
        if not self.auto_approve:
            # L3: 限時信任窗口（攞過一次 consent，限期 + 預算內唔使再攞）
            if self._check_pair_grant(sender, receiver):
                self.bus.append({**envelope, "delivery": "RELAYED_GRANT"})
                self._index_message(envelope)
                print(f"  [GRANT-RELAY] {sender} → {receiver}  [{intent}]"
                      f"  msg_id={envelope.get('msg_id','?')}（信任窗口放行）")
                return 200, "OK: envelope 已轉發（L3 信任窗口）", None

            # L2: 對話鏈同意（已批准任務嘅後續往來）
            if self._check_conversation(envelope):
                self.bus.append({**envelope, "delivery": "RELAYED_CONVERSATION"})
                self._index_message(envelope)
                print(f"  [CONV-RELAY] {sender} → {receiver}  [{intent}]"
                      f"  msg_id={envelope.get('msg_id','?')}（對話鏈放行）")
                return 200, "OK: envelope 已轉發（L2 對話鏈）", None

            # L1: 逐條訊息批准（預設）
            msg_id = envelope.get("msg_id")
            if not msg_id:
                return 400, "BAD_REQUEST: 缺 msg_id", None
            self._expire_pending()
            with self.pending_lock:
                # SEC-02: 拒絕重複 msg_id，防 pending 訊息被掉包
                if msg_id in self.pending_approvals:
                    return 409, f"CONFLICT: msg_id={msg_id} 已在待批准列表，唔准覆寫", None
                if len(self.pending_approvals) >= MAX_PENDING:
                    return 429, "TOO_MANY_PENDING: 待批准隊列已滿，請先處理", None
                # P0-04: 入 pending 嗰陣就計好不可變 envelope hash
                self.pending_approvals[msg_id] = {
                    "envelope": envelope,
                    "received": time.time(),
                    "hash": envelope_hash(envelope),
                }
            self.bus.append({**envelope, "delivery": "PENDING_APPROVAL"},
                            deliver=False)
            print(f"  [GATE] {sender} → {receiver}  [{intent}]  msg_id={msg_id}  待批准")
            return 202, f"PENDING_APPROVAL: msg_id={msg_id}，等待管理員批准（POST /approve）", \
                   {"msg_id": msg_id, "pending": True}

        # --- 轉發 ---
        self.bus.append({**envelope, "delivery": "RELAYED"})
        self._index_message(envelope)
        print(f"  [RELAY] {sender} → {receiver}  [{intent}]  msg_id={envelope.get('msg_id','?')}")

        return 200, "OK: envelope 已轉發", None

    def handle_register(self, body):
        """註冊新 agent。SEC-01: 已存在返回 409，唔會洩漏現有 secret。"""
        agent_id = body.get("agent_id")
        display_name = body.get("display_name", agent_id)
        if not agent_id:
            return 400, "BAD_REQUEST: 缺 agent_id", None

        info, created = self.registry.register(agent_id, display_name)
        if not created:
            return 409, f"CONFLICT: agent '{agent_id}' 已存在", None
        return 200, "OK", {
            "agent_id": agent_id,
            "secret": info["secret"],
            "read_token": info["read_token"],
            "display_name": info["display_name"],
        }

    def handle_allow(self, body):
        agent_a = body.get("agent_a")
        agent_b = body.get("agent_b")
        if not agent_a or not agent_b:
            return 400, "BAD_REQUEST: 缺 agent_a 或 agent_b", None
        if not self.registry.allow(agent_a, agent_b):
            return 404, "NOT_FOUND: agent_a 或 agent_b 未註冊", None
        return 200, "OK", {"allowed": f"{agent_a} ↔ {agent_b}"}

    def handle_kill(self):
        self.killed = True
        # P0-02: 撤銷所有 active L3 grants（RESUME 唔會令佢哋復活）
        with self.consent_lock:
            revoked = len(self.pair_grants)
            self.pair_grants.clear()
        # P0-02: 持久化 stopped 狀態（restart 仍 STOPPED）
        self._save_state()
        self.bus.append({"event": "KILL_SWITCH", "grants_revoked": revoked,
                         "delivery_ts": datetime.now(timezone.utc).isoformat()})
        return 200, "KILLED: 所有通信已終止（持久化，restart 後仍 STOPPED）", None

    def handle_resume(self):
        # P0-02: 只恢復 Gateway，唔會令已撤銷嘅舊 grant 自動生效
        if not self.killed:
            return 200, "RESUME: relay 本身未處於 STOPPED，無需 resume", None
        self.killed = False
        self._save_state()
        self.bus.append({"event": "RESUME",
                         "delivery_ts": datetime.now(timezone.utc).isoformat()})
        return 200, ("RESUMED: Gateway 已恢復"
                     "（舊 grant 唔會自動復活，需重新 /grant）"), None

    def handle_rotate_token(self):
        """P1-02: 輪換 admin token。舊 token 即時失效，返回新 token（只畀已認證 admin）。"""
        new_token = secrets.token_hex(16)
        self.admin_token = new_token
        # 若自動生成模式，同步更新 token 檔（0600）
        try:
            if ADMIN_TOKEN_FILE.exists():
                ADMIN_TOKEN_FILE.write_text(new_token, encoding="utf-8")
                os.chmod(ADMIN_TOKEN_FILE, 0o600)
        except OSError:
            pass
        self.bus.append({"event": "TOKEN_ROTATED",
                         "delivery_ts": datetime.now(timezone.utc).isoformat()},
                        deliver=False)
        return 200, "TOKEN_ROTATED: 舊 admin token 已失效，請用新 token", \
               {"admin_token": new_token}

    def handle_pending(self):
        """列出待批准訊息。"""
        self._expire_pending()
        items = []
        with self.pending_lock:
            for msg_id, e in self.pending_approvals.items():
                env = e["envelope"]
                items.append({
                    "msg_id": msg_id,
                    "sender": env.get("sender"),
                    "receiver": env.get("receiver"),
                    "intent_type": env.get("intent_type"),
                    "payload_preview": str(env.get("payload", ""))[:120],
                    "envelope_hash": e["hash"],  # P0-04: 不可變 hash 俾 dashboard
                })
        return 200, "OK", {"pending": items, "count": len(items)}

    def _revalidate_for_approval(self, envelope, received_epoch):
        """P0-03: 批准前重新驗證（消息喺 pending 可能擺咗幾分鐘）。
        返回 (ok, reason)。fail-closed：任何一項唔過就拒絕批准。"""
        # 1. relay 是否被 kill
        if self.killed:
            return False, "relay 已 STOPPED（kill-switch）"
        sender = envelope.get("sender")
        receiver = envelope.get("receiver")
        # 2. 雙方註冊
        if self.registry.get_agent(sender) is None or \
                self.registry.get_agent(receiver) is None:
            return False, "sender 或 receiver 已取消註冊"
        # 3. ACL（policy 可能改變）
        if not self.registry.check_acl(sender, receiver):
            return False, "ACL 已變更，雙方不再互信"
        # 4. 簽名完整性（防 pending 期間被篡改）
        sig_ok, sig_reason = self._verify_sig(envelope)
        if not sig_ok:
            return False, sig_reason
        # 5. 時間戳新鮮度（pending 太久就過期）
        fresh_ok, fresh_reason = self._check_freshness(envelope)
        if not fresh_ok:
            return False, f"訊息已過期（{fresh_reason}）"
        # 6. pending TTL（入 queue 到而家）
        if time.time() - received_epoch > PENDING_TTL_SECONDS:
            return False, f"pending 超過 {PENDING_TTL_SECONDS}s 未處理，已過期"
        return True, "OK"

    def handle_approve(self, body):
        """批准一條待批准訊息，轉發畀 receiver。
        v0.3.1: scope=once（預設，SEC-17 最小權限）只放呢一條；
                scope=conversation 明確要求先會開對話鏈同意（L2）。
        P0-03: 批准前重新驗證（kill / 註冊 / ACL / freshness / TTL / 簽名）。
        P0-04: 批准時重新計算 envelope hash 並比對，綁定不可變 envelope。
        """
        msg_id = body.get("msg_id")
        if not msg_id:
            return 400, "BAD_REQUEST: 缺 msg_id", None
        scope = body.get("scope", "once")  # SEC-17: 預設最小權限，開鏈要明確講
        if scope not in ("once", "conversation"):
            return 400, "BAD_REQUEST: scope 要係 once / conversation", None
        with self.pending_lock:
            entry = self.pending_approvals.pop(msg_id, None)
        if entry is None:
            return 404, f"NOT_FOUND: msg_id={msg_id} 不在待批准列表", None

        envelope = entry["envelope"]

        # P0-03: 批准前重新驗證（消息喺 pending 可能擺咗幾分鐘）
        ok, reason = self._revalidate_for_approval(envelope, entry["received"])
        if not ok:
            self.bus.append({**envelope, "delivery": f"APPROVAL_REJECTED:{reason}"},
                            deliver=False)
            return 409, f"APPROVAL_REJECTED: {reason}", None

        # P0-04: 重新計算 envelope hash，確保待批准期間 envelope 未被掉包
        if envelope_hash(envelope) != entry["hash"]:
            self.bus.append({**envelope, "delivery": "APPROVAL_REJECTED:HASH_MISMATCH"},
                            deliver=False)
            return 409, "APPROVAL_REJECTED: envelope hash 唔匹配（可能被篡改）", None

        # P0-04: 獨立 consent 記錄（同 agent signature / relay delivery 分開）
        consent_id = f"consent-{uuid.uuid4().hex}"
        self._adopt_into_conversation(envelope, scope)
        self.bus.append({**envelope, "delivery": "APPROVED_RELAYED",
                         "consent_id": consent_id})
        self._index_message(envelope)
        sender = envelope.get("sender", "?")
        receiver = envelope.get("receiver", "?")
        intent = envelope.get("intent_type", "?")
        print(f"  [APPROVE] {sender} → {receiver}  [{intent}]  msg_id={msg_id}"
              f"  consent_id={consent_id}  已批准轉發（scope={scope}）")
        return 200, f"APPROVED: msg_id={msg_id} 已轉發", \
                   {"msg_id": msg_id, "scope": scope, "consent_id": consent_id}

    def handle_reject(self, body):
        """拒絕一條待批准訊息。"""
        msg_id = body.get("msg_id")
        if not msg_id:
            return 400, "BAD_REQUEST: 缺 msg_id", None
        with self.pending_lock:
            entry = self.pending_approvals.pop(msg_id, None)
        if entry is None:
            return 404, f"NOT_FOUND: msg_id={msg_id} 不在待批准列表", None

        envelope = entry["envelope"]
        self.bus.append({**envelope, "delivery": "REJECTED_BY_GATE"})
        return 200, f"REJECTED: msg_id={msg_id} 已拒絕", {"msg_id": msg_id}


# ---------------------------------------------------------------------------
# Auth Helpers
# ---------------------------------------------------------------------------

def extract_bearer_token(headers):
    """從 HTTP headers 拎 Bearer token。"""
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def mask_token(token):
    """SEC-11: token 只顯示頭尾各 4 位。"""
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}...{token[-4:]}"


def _load_or_create_key(path):
    """P1-07: 載入或生成一個持久化 hex key（0600）。用於 audit HMAC 鏈。"""
    p = Path(path)
    try:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
        key = secrets.token_hex(32)
        p.write_text(key, encoding="utf-8")
        os.chmod(p, 0o600)
        return key
    except OSError:
        return secrets.token_hex(32)  # 退化：每次隨機（跨重啟鏈會斷，只影響 verify）


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class RelayHTTPHandler(BaseHTTPRequestHandler):
    relay: BilogueRelay = None  # set by server factory
    protocol_version = "HTTP/1.1"
    _slots = threading.BoundedSemaphore(MAX_WORKER_THREADS)  # SEC-16

    def setup(self):
        super().setup()
        # SEC-16: 防 slow-loris——每個連線嘅讀寫都有 timeout
        self.request.settimeout(REQUEST_TIMEOUT_SECONDS)

    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_admin(self):
        """檢查 admin token。SEC-06: 用 compare_digest 防 timing attack。
        P1-02: 附帶 admin 端點速率限制（按 IP）。"""
        ip = self.client_address[0]
        if not self.relay.rate_admin.allow("a:" + ip):
            self.relay.rate_limited_total += 1
            self._send_json(429, {"error": "rate limit exceeded (admin)"})
            return False
        token = extract_bearer_token(self.headers)
        if not token or not hmac.compare_digest(token, self.relay.admin_token):
            self._send_json(403, {"error": "admin token required",
                                  "hint": "Authorization: Bearer <admin_token>"})
            return False
        return True

    def _check_agent_auth(self, agent_id):
        """驗證 agent 嘅 inbox read_token。
        SEC-09: 用獨立 read_token，唔係簽名 secret。
        SEC-12: 未知 agent 同錯 token 一律 403，唔洩漏 agent 存唔存在。
        """
        token = extract_bearer_token(self.headers)
        agent = self.relay.registry.get_agent(agent_id)
        if agent is None or not token or \
                not hmac.compare_digest(token, agent["read_token"]):
            self._send_json(403, {"error": "agent authentication required",
                                  "hint": "Authorization: Bearer <read_token>"})
            return False
        return True

    def _read_body(self):
        """安全讀取 request body。
        SEC-03: Content-Length 安全解析 + 1MB 上限。
        返回 (ok, body_dict)。
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0) or 0)
        except (ValueError, TypeError):
            self._send_json(400, {"error": "invalid Content-Length"})
            return False, None
        if content_length > MAX_BODY_BYTES:
            self._send_json(413, {"error": f"payload too large (max {MAX_BODY_BYTES} bytes)"})
            return False, None
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            return True, json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return False, None
        except UnicodeDecodeError:
            # P2-04: 二進位 / 非 UTF-8 body（json.loads 會拋 UnicodeDecodeError，
            # 唔係 JSONDecodeError）→ 400 而唔係 500
            self._send_json(400, {"error": "invalid JSON (body must be UTF-8)"})
            return False, None

    def _rate_global(self):
        """P1-02 / P1-05: 全局滑動窗口限速（按 client IP）。超額返回 429。"""
        ip = self.client_address[0]
        if not self.relay.rate_global.allow("g:" + ip):
            self.relay.rate_limited_total += 1
            try:
                self._send_json(429, {"error": "rate limit exceeded (global)"})
            except Exception:
                pass
            return False
        return True

    def do_GET(self):
        # SEC-13: 全域兜底，未捕捉異常返回 500 而唔係 cut 連線
        # SEC-16: 線程槽上限，滿咗即 503，防線程耗盡
        if not self._slots.acquire(blocking=False):
            try:
                self._send_json(503, {"error": "server busy, retry later"})
            except Exception:
                pass
            return
        if not self._rate_global():  # P1-02/P1-05 全局限速
            self._slots.release()
            return
        try:
            self._do_GET()
        except Exception:  # P2-02: 對外錯誤泛型化，唔洩漏異常類名/堆棧
            try:
                self._send_json(500, {"error": "internal server error"})
            except Exception:
                pass
        finally:
            self._slots.release()

    def do_POST(self):
        if not self._slots.acquire(blocking=False):
            try:
                self._send_json(503, {"error": "server busy, retry later"})
            except Exception:
                pass
            return
        if not self._rate_global():  # P1-02/P1-05 全局限速
            self._slots.release()
            return
        try:
            self._do_POST()
        except Exception:  # P2-02: 泛型化
            try:
                self._send_json(500, {"error": "internal server error"})
            except Exception:
                pass
        finally:
            self._slots.release()

    def _do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # --- 公開端點 ---
        if path == "/health":
            # SEC-05: 精簡到只返 status，唔再洩漏 agent 名單 / ACL / pending 數
            self._send_json(200, {
                "status": "alive" if not self.relay.killed else "killed",
            })
            return

        # P1-08: 健康檢查（比 /health 多啲，但仍公開、唔洩漏敏感資料）
        if path == "/healthz":
            r = self.relay
            inbox_total = sum(
                len([it for it in q if it["ack_state"] == "DELIVERED_NOT_ACK"])
                for q in r.bus.queues.values()
            )
            self._send_json(200, {
                "status": "alive" if not r.killed else "stopped",
                "version": RELAY_VERSION,
                "killed": r.killed,
                "using_encryption": bool(r.crypto and r.crypto.using_encryption),
                "pending": len(r.pending_approvals),
                "inbox_undelivered": inbox_total,
            })
            return

        # P1-08: metrics（公開，聚合計數；唔含 agent 內容）
        if path == "/metrics":
            r = self.relay
            now = time.time()
            grants = sum(1 for g in r.pair_grants.values()
                         if now < g["expires"])
            inbox_total = sum(len(q) for q in r.bus.queues.values())
            self._send_json(200, {
                "version": RELAY_VERSION,
                "pending_approvals": len(r.pending_approvals),
                "active_grants": grants,
                "active_conversations": len(r.conversations),
                "inbox_messages": inbox_total,
                "nonces_seen": len(r.registry.seen_nonces),
                "rate_limited_total": r.rate_limited_total,
                "using_encryption": bool(r.crypto and r.crypto.using_encryption),
            })
            return

        # P1-07: 審計日誌完整性驗證（admin-only）
        if path == "/audit/verify":
            if not self._check_admin():
                return
            ok, bad = self.relay.bus.verify_audit_log()
            self._send_json(200, {
                "integrity": "intact" if ok else "TAMPERED",
                "ok": ok,
                "first_bad_line": bad,
            })
            return

        # --- SEC-05: /acl 改為 admin-only ---
        if path == "/acl":
            if not self._check_admin():
                return
            self._send_json(200, {
                a: list(buddies) for a, buddies in self.relay.registry.acl.items()
            })
            return

        # --- inbox 需要 agent read_token 認證 ---
        if path.startswith("/inbox/"):
            agent_id = path.split("/inbox/")[1]
            if not self._check_agent_auth(agent_id):
                return
            # SEC-04: parse_qs 正規解析，畸形 since 返回 400
            query = parse_qs(parsed.query)
            since = 0
            if "since" in query:
                try:
                    since = int(query["since"][0])
                    if since < 0:
                        raise ValueError
                except (ValueError, IndexError):
                    self._send_json(400, {"error": "invalid 'since' parameter"})
                    return
            msgs = self.relay.bus.fetch_inbox(agent_id)  # P0-05: 唔即刪，等 ACK
            self._send_json(200, {"messages": msgs, "count": len(msgs)})
            return

        # --- admin 端點 ---
        if path == "/pending":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_pending()
            self._send_json(code, {"message": msg, **(data or {})})
            return

        # v0.3: 列出活躍 consent grants
        if path == "/grants":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_grants()
            self._send_json(code, {"message": msg, **(data or {})})
            return

        self._send_json(404, {"error": "not found"})

    def _do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        ok, body = self._read_body()
        if not ok:
            return
        # 防禦：POST body 必須係 JSON object，否則直接 400（唔使逐 handler 判斷，避免 500）
        if not isinstance(body, dict):
            self._send_json(400, {"error": "request body must be a JSON object"})
            return
        # 防禦：常見字串欄位若係 array / object 會令 dict 查詢 TypeError → 500；
        # 一律預檢，畸形就 400（P1-04 加固）
        for field in ("msg_id", "agent_id", "agent_a", "agent_b", "grant_id",
                      "sender", "receiver", "intent_type", "nonce", "ts",
                      "sig", "in_reply_to", "direction", "scope", "read_token",
                      "display_name"):
            v = body.get(field)
            if v is not None and not isinstance(v, str):
                self._send_json(400, {"error": f"bad field '{field}': expected string"})
                return

        # --- /send: 任何 agent 都可以提交（簽名 + nonce + ACL 把關） ---
        if path == "/send":
            # P1-02/P1-05: 每 IP 嘅 send 速率限制（DoS 防護）
            ip = self.client_address[0]
            if not self.relay.rate_send.allow("s:" + ip):
                self.relay.rate_limited_total += 1
                self._send_json(429, {"error": "rate limit exceeded (send)"})
                return
            code, msg, data = self.relay.handle_send(body)
            self._send_json(code, {"message": msg, "msg_id": body.get("msg_id"),
                                   **(data or {})})
            return

        # --- admin 端點（需要 admin token） ---
        if path == "/register":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_register(body)
            self._send_json(code, {"message": msg, **(data or {})})
            return

        # P1-02: admin token 輪換（舊 token 即時失效）
        if path == "/rotate-token":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_rotate_token()
            self._send_json(code, {"message": msg, **(data or {})})
            return

        if path == "/allow":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_allow(body)
            self._send_json(code, {"message": msg, **(data or {})})
            return

        if path == "/kill":
            if not self._check_admin():
                return
            code, msg, _ = self.relay.handle_kill()
            self._send_json(code, {"message": msg})
            return

        if path == "/resume":
            if not self._check_admin():
                return
            code, msg, _ = self.relay.handle_resume()
            self._send_json(code, {"message": msg})
            return

        # P0-05: Inbox ACK —— POST /messages/{agent_id}/{msg_id}/ack
        if path.startswith("/messages/") and path.endswith("/ack"):
            seg = path[len("/messages/"):].split("/")
            if len(seg) == 3 and seg[2] == "ack":
                agent_id, msg_id = seg[0], seg[1]
                if not self._check_agent_auth(agent_id):
                    return
                if self.relay.bus.ack_message(agent_id, msg_id):
                    self._send_json(200, {"message": f"ACKED: {msg_id}",
                                          "msg_id": msg_id})
                else:
                    self._send_json(404, {"error": "msg_id 唔喺未 ACK 隊列"
                                                  "（可能已 ACK 或唔存在）"})
                return

        if path == "/approve":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_approve(body)
            self._send_json(code, {"message": msg, **(data or {})})
            return

        if path == "/reject":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_reject(body)
            self._send_json(code, {"message": msg, **(data or {})})
            return

        # v0.3: L3 限時信任窗口
        if path == "/grant":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_grant(body)
            self._send_json(code, {"message": msg, **(data or {})})
            return

        if path == "/revoke":
            if not self._check_admin():
                return
            code, msg, data = self.relay.handle_revoke(body)
            self._send_json(code, {"message": msg, **(data or {})})
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print(f"  [HTTP] {self.address_string()} {fmt % args}")


def make_server(port, auto_approve, admin_token=None, host="127.0.0.1",
                state_file=None, crypto_store=None, audit_key=None,
                tls_cert=None, tls_key=None, tls_client_ca=None, inbox_path=None):
    relay = BilogueRelay(auto_approve=auto_approve, admin_token=admin_token,
                         state_file=state_file, crypto_store=crypto_store,
                         audit_key=audit_key, inbox_path=inbox_path)
    RelayHTTPHandler.relay = relay
    server = ThreadingHTTPServer((host, port), RelayHTTPHandler)  # P0-01: 預設 127.0.0.1
    server.allow_reuse_address = True
    server.daemon_threads = True
    # P1-01: TLS —— 提供 cert/key 就用 HTTPS（可選 mTLS）
    if tls_cert and tls_key:
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
        if tls_client_ca:  # mTLS：要求客戶端證書
            ctx.load_verify_locations(cafile=tls_client_ca)
            ctx.verify_mode = _ssl.CERT_REQUIRED
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    return server, relay


# ---------------------------------------------------------------------------
# Demo Client — 模擬兩個 agent 通過 relay 通信
# ---------------------------------------------------------------------------

def run_relay_demo(port, auto_approve, admin_token):
    """啟動 relay 之後，跑一個 mock demo。"""
    import urllib.request
    import urllib.error

    base = f"http://localhost:{port}"

    def post(path, data, token=None):
        body = json.dumps(data).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            f"{base}{path}", data=body, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def get(path, token=None):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{base}{path}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def make_envelope(sender, secret, receiver, intent, payload):
        env = {
            "msg_id": f"msg-{uuid.uuid4().hex}",  # P0-06: full UUID
            "sender": sender,
            "receiver": receiver,
            "intent_type": intent,
            "payload": payload,
            "in_reply_to": None,
            "nonce": uuid.uuid4().hex,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        env["sig"] = crypto_sign(env, secret)  # P0-07: shared module
        return env

    # 等 server 啟動
    time.sleep(0.5)

    print("\n" + "=" * 60)
    print("  BILOGUE RELAY DEMO v0.3 — 跨 agent 通信（含安全測試）")
    print("=" * 60)

    # 0. Health check（v0.2.1 起只返 status）
    _, health = get("/health")
    print(f"\n  [Health] {health['status']}")

    # 1. 註冊第三個 agent（admin token 認證）
    code, reg = post("/register",
                     {"agent_id": "danny", "display_name": "Danny (策劃助手)"},
                     token=admin_token)
    print(f"\n  [Register] code={code} Danny → secret: {mask_token(reg.get('secret','?'))}")
    if code != 200:
        print("  [DEMO] 註冊失敗，demo 終止")
        return

    # 2. ACL 授權（admin token 認證）
    code, allow = post("/allow", {"agent_a": "karina", "agent_b": "danny"},
                       token=admin_token)
    print(f"  [ACL] code={code} {allow.get('allowed', allow.get('message', '?'))}")

    # demo 用：直接由 registry 拎 secret / read_token（實際部署只有註冊時先會攞到）
    karina_secret = relay_for_demo.registry.get_agent("karina")["secret"]
    stfund_read_token = relay_for_demo.registry.get_agent("stfund")["read_token"]

    # 3. Karina → St.Fund: DELEGATE（含 nonce + ts）
    env = make_envelope("karina", karina_secret, "stfund", "DELEGATE",
                        {"task": "Q3 財務分析大綱，請核數"})
    code, result = post("/send", env)
    print(f"\n  [Send] karina → stfund [DELEGATE]: code={code} {result['message']}")

    if auto_approve:
        # 4. St.Fund 收信（read_token 認證，讀完即清）
        code, inbox = get("/inbox/stfund", token=stfund_read_token)
        print(f"  [Inbox] stfund code={code} 有 {inbox['count']} 條新訊息")
        if inbox["messages"]:
            msg = inbox["messages"][-1]
            print(f"         最新: {msg['sender']} → {msg['receiver']} [{msg['intent_type']}]")

    # 5. 篡改測試
    print("\n  [Security] 篡改測試...")
    tampered = make_envelope("karina", karina_secret, "stfund", "DELEGATE",
                             {"task": "惡意任務!!!"})
    tampered["sig"] = env["sig"]  # 用舊簽名
    code_t, tamper_r = post("/send", tampered)
    print(f"  [Tamper] code={code_t} {tamper_r['message']}")

    # 6. Replay 測試
    print("\n  [Security] Replay 測試...")
    code_r, replay_r = post("/send", env)  # 同一條 envelope 再 send
    print(f"  [Replay] code={code_r} {replay_r['message']}")

    # 7. Inbox 認證測試（無 token）
    print("\n  [Security] Inbox 認證測試（無 token）...")
    code_n, inbox_n = get("/inbox/stfund")  # 冇 token
    print(f"  [NoAuth] code={code_n} {inbox_n.get('error', '?')}")

    # 8. Kill-switch 測試（admin token 認證）
    if auto_approve:
        print("\n  [Kill] 觸發 kill-switch...")
        code_k, kill_r = post("/kill", {}, token=admin_token)
        print(f"  [Kill] code={code_k} {kill_r['message']}")
        env2 = make_envelope("karina", karina_secret, "stfund", "DELEGATE",
                             {"task": "kill 之後仲想 send？"})
        code2, result2 = post("/send", env2)
        print(f"  [After] code={code2} {result2['message']}")

    print("\n" + "=" * 60)
    print("  RELAY DEMO 完成")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

relay_for_demo = None  # 全域，畀 demo 用

ADMIN_TOKEN_FILE = Path(__file__).parent / "relay_admin_token.txt"


def main():
    global relay_for_demo

    parser = argparse.ArgumentParser(
        description="Bilogue HTTP Relay Server v0.3.3 (Route A)"
    )
    parser.add_argument("--port", type=int, default=8420,
                        help="relay server port (default 8420)")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="bind address（預設 127.0.0.1 只綁本機；"
                             "要 LAN 訪問先明確填 --host 0.0.0.0）")
    parser.add_argument("--auto-approve", action="store_true",
                        help="自動批准所有通信（測試用）")
    parser.add_argument("--admin-token", type=str, default=None,
                        help="admin token（預設自動生成，可用環境變數 BILOGUE_ADMIN_TOKEN）")
    parser.add_argument("--state-file", type=str, default=str(STATE_FILE),
                        help="kill-switch 持久化狀態檔（P0-02）")
    parser.add_argument("--inbox", type=str, default=str(INBOX_PATH),
                        help="audit/inbox JSONL 路徑（測試隔離用，默認 relay_inbox.jsonl）")
    parser.add_argument("--crypto-key-file", type=str, default=str(CRYPTO_KEY_FILE),
                        help="P1-03 磁碟加密 key 路徑（Fernet，0600）")
    parser.add_argument("--audit-key-file", type=str, default=str(AUDIT_KEY_FILE),
                        help="P1-07 audit HMAC 鏈 key 路徑（0600）")
    parser.add_argument("--demo", action="store_true",
                        help="啟動後跑 demo client")
    # P1-01: TLS（非 loopback 綁定必須提供，否則拒絕啟動）
    parser.add_argument("--tls-cert", type=str, default=None,
                        help="TLS 伺服器證書（PEM）。非 loopback 綁定必須提供")
    parser.add_argument("--tls-key", type=str, default=None,
                        help="TLS 私鑰（PEM）")
    parser.add_argument("--tls-client-ca", type=str, default=None,
                        help="可選 mTLS：信任嘅客戶端 CA（要求客戶端證書）")
    parser.add_argument("--allow-insecure-lan", action="store_true",
                        help="P1-01: 明知冇 TLS 都強行喺非 loopback 綁定"
                             "（極唔推薦，只適臨時測試）")
    args = parser.parse_args()

    # P2-03: 啟動時校驗配置（fail-closed）
    try:
        validate_config()
    except ValueError as e:
        print(f"\n  ❌  配置校驗失敗，拒絕啟動：\n{e}\n")
        sys.exit(2)

    # admin token：CLI 參數 > 環境變數 > 自動生成
    admin_token = args.admin_token or os.environ.get("BILOGUE_ADMIN_TOKEN")
    auto_generated = admin_token is None

    # P0-01 + P1-01: 非 loopback 綁定 —— 必須 TLS，否則拒絕啟動（除非顯式 --allow-insecure-lan）
    host = args.host
    LOOPBACK = ("127.0.0.1", "localhost", "::1")
    has_tls = bool(args.tls_cert and args.tls_key)
    if host not in LOOPBACK:
        if not has_tls:
            if args.allow_insecure_lan:
                print("\n  ⚠️  WARNING: 非 localhost 綁定但無 TLS，且你用咗"
                      " --allow-insecure-lan 強行啟動。")
                print("  ⚠️  signing secret / read token / payload / admin token"
                      " 會經未加密網絡傳送！")
                print("  ⚠️  絕唔可以喺生產 / 暴露去 LAN 或 Internet 咁做。\n")
            else:
                print("\n  ❌  P1-01: Relay 要綁定非 localhost 介面（%s），"
                      "但無提供 --tls-cert / --tls-key。" % host)
                print("  ❌  為咗唔會以明文 HTTP 暴露敏感資料，已拒絕啟動。")
                print("  ❌  請提供 TLS 證書，或用 --host 127.0.0.1（localhost）。")
                print("  ❌  如果係臨時測試，可以加 --allow-insecure-lan（極唔推薦）。\n")
                sys.exit(3)
        else:
            print("\n  🔒  TLS 已啟用（HTTPS），非 localhost 綁定 OK。")
            if args.tls_client_ca:
                print("  🔒  mTLS 已啟用：客戶端必須提供受信任證書。\n")
            else:
                print("  ⚠️  建議加 --tls-client-ca 啟用 mTLS（雙向認證）。\n")

    # P1-03: 磁碟加密 store（cryptography 可用時加密 audit/state）
    crypto_store = CryptoStore(Path(args.crypto_key_file))
    # P1-07: audit HMAC 鏈 key（持久化，獨立於 crypto key）
    audit_key = _load_or_create_key(Path(args.audit_key_file))

    state_file = Path(args.state_file)
    inbox_path = Path(args.inbox)

    server, relay = make_server(args.port, args.auto_approve, admin_token,
                                host=host, state_file=state_file,
                                crypto_store=crypto_store, audit_key=audit_key,
                                tls_cert=args.tls_cert, tls_key=args.tls_key,
                                tls_client_ca=args.tls_client_ca,
                                inbox_path=inbox_path)
    relay_for_demo = relay

    # P0-02: 如果之前被 kill 過，restart 後仍 STOPPED
    if relay.killed:
        print("  ⛔  RELAY 之前被 KILL-SWITCH 停過，現於 STOPPED 狀態。")
        print("  ⛔  POST /resume（admin token）先可以恢復通信；舊 grant 唔會自動復活。\n")

    # SEC-11: 唔再明文打印 token。自動生成嘅寫入 0600 檔案，stdout 只顯示遮罩版。
    token_source = "--admin-token" if args.admin_token else \
        ("BILOGUE_ADMIN_TOKEN" if not auto_generated else "auto-generated")
    if auto_generated:
        try:
            ADMIN_TOKEN_FILE.write_text(relay.admin_token, encoding="utf-8")
            os.chmod(ADMIN_TOKEN_FILE, 0o600)
            token_hint = f"已寫入 {ADMIN_TOKEN_FILE}（權限 0600）"
        except OSError as e:
            token_hint = f"寫入 {ADMIN_TOKEN_FILE} 失敗：{e}"
    else:
        token_hint = "（由你提供，唔會落 log）"

    print(f"\n  Bilogue Relay Server v0.3.3 啟動")
    print(f"  Bind: {host}:{args.port}  （P0-01: 預設只綁 localhost）")
    print(f"  Auto-approve: {args.auto_approve}")
    print(f"  TLS: {'ON (HTTPS)' if has_tls else 'OFF (HTTP, localhost only)'}")
    print(f"  Disk encryption: {'ON (Fernet)' if crypto_store.using_encryption else 'OFF (plaintext)'}")
    print(f"  Admin Token: {mask_token(relay.admin_token)}  [{token_source}] {token_hint}")
    print(f"  Inbox: {inbox_path}")
    print(f"  State: {state_file}  （P0-02: kill-switch 持久化）")
    print(f"\n  端點:")
    print(f"    POST /send          — 提交 envelope（簽名 + nonce + ACL 把關）")
    print(f"    GET  /inbox/{{aid}}   — 拎未 ACK 訊息（需 Bearer: read_token）")
    print(f"    POST /messages/{{aid}}/{{mid}}/ack — ACK 一條 inbox 訊息（需 Bearer: read_token）")
    print(f"    POST /register       — 註冊 agent（需 Bearer: admin token，重複返回 409）")
    print(f"    POST /allow          — ACL 授權（需 Bearer: admin token）")
    print(f"    GET  /health         — 健康檢查（公開，只返 status）")
    print(f"    GET  /healthz        — 健康檢查 v2（版本 + 加密狀態，公開）")
    print(f"    GET  /metrics        — 聚合 metrics（公開）")
    print(f"    GET  /acl            — 睇 ACL（需 Bearer: admin token）")
    print(f"    POST /kill           — kill-switch（需 Bearer: admin token）")
    print(f"    POST /resume         — 恢復通信（需 Bearer: admin token；唔會令舊 grant 復活）")
    print(f"    GET  /pending        — 待批准列表（需 Bearer: admin token）")
    print(f"    POST /approve        — 批准訊息（需 Bearer: admin token）")
    print(f"    POST /reject         — 拒絕訊息（需 Bearer: admin token）")
    print(f"    POST /grant          — L3 限時信任窗口（需 Bearer: admin token）")
    print(f"    POST /revoke         — 撤銷信任窗口（需 Bearer: admin token；P1-06 通知 receiver）")
    print(f"    GET  /grants         — 活躍信任窗口列表（需 Bearer: admin token）")
    print(f"    POST /rotate-token   — 輪換 admin token（需 Bearer: admin token，P1-02）")
    print(f"    GET  /audit/verify   — 審計日誌完整性驗證（需 Bearer: admin token，P1-07）")
    print(f"\n  按 Ctrl+C 停止\n")

    if args.demo:
        def _demo():
            try:
                run_relay_demo(args.port, args.auto_approve, relay.admin_token)
            except Exception as e:
                print(f"  [DEMO ERROR] {e}")
        threading.Thread(target=_demo, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Relay 已停止")
        server.server_close()


if __name__ == "__main__":
    main()
