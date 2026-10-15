# Bilogue Protocol

> **AI-to-AI 通信協定，帶人類批准位（Consent Gate）。**
>
> 核心論點：**模型係引擎，Agent ID 係電話號碼。** 轉 model = 換引擎，號碼唔使換。
>
> **定位：Bilogue 唔係要取代 MCP、A2A 等大標準，而係佢哋之上嘅「人類批准＋稽核治理層」。**
> MCP 解決 agent 點樣用工具，A2A 解決 agent 之間點樣傳訊息——但冇一個標準規定「部機真係做嘢之前，要有個人撳掣」。Bilogue 就係補呢個位：任何 agent 喺執行有副作用嘅動作之前，都要經過 Consent Gate；做完嘅嘢，全部寫入 append-only audit log，方便事後追查。

[![Tests](https://img.shields.io/badge/tests-99%20security--regression-passing-brightgreen)]()
[![Fuzz](https://img.shields.io/badge/fuzz-600%20iters%200%20crash-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-yellow)]()
[![Security](https://img.shields.io/badge/security-v0.3.3%20self--audited-brightgreen)]()

> **WARNING: This is an EXPERIMENTAL PROTOTYPE. It HAS been self-security-audited by the project author (3 rounds, 20 findings: P0×8 / P1×8 / P2×4 — all fixed in v0.3.3), but it has NOT been audited by an independent third party and is NOT certified production-ready.** LAN / Internet deployment REQUIRES TLS (`--tls-cert` / `--tls-key`; binding to a non-loopback interface without TLS is now **refused**). See [SECURITY.md](SECURITY.md) for residual risks.

## 這是什麼？

Bilogue 是一個讓多個 AI Agent 互相通訊的協定和參考實作。它不解決「AI 能不能對話」的問題（那是幾十行 code 的事），而是把這些膠水**標準化**：

| 層 | 解決的問題 | 實作 |
|---|---|---|
| **Identity** | 誰是誰？模型換了怎麼辦？ | Agent ID + HMAC 簽名，ACL 認 ID 不認模型 |
| **Intent** | AI 之間講什麼？格式是什麼？ | Intent Envelope：DELEGATE → PROPOSE → ACCEPT → REPORT |
| **Consent** | 人類在哪裡批准？ | Consent Gate：每條外部通信彈出 y/n，`stop` 即 kill-switch |
| **Audit** | 出了事怎麼查？ | JSONL append-only audit log |

## 一鍵跑起來

```bash
# 本地 demo（冇 API key，mock 模式 + 自動批准）
python3 hello_bilogue.py --mock --auto-approve

# 跑安全 + Consent 回歸測試（99 項）
python3 test_relay_security.py

# 跑模糊測試（P2-04：600 次畸形請求，要求零 crash / 零 500）
python3 fuzz_relay.py --iters 600

# 啟動 HTTP Relay Server（預設只綁 localhost，跨 agent 通信）
python3 bilogue_relay.py --port 8420

# 跨機器部署（必須 TLS；無 TLS 綁非 loopback 會直接拒絕啟動，exit 3）
python3 bilogue_relay.py --port 8420 --host 0.0.0.0 \
  --tls-cert /path/fullchain.pem --tls-key /path/privkey.pem
```

## 快速上手

### 1. 兩個 Agent 對話

```python
from hello_bilogue import AgentRegistry, MessageBus, ConsentGate, Agent

registry = AgentRegistry()
bus = MessageBus()
gate = ConsentGate(auto_approve=True)

registry.register("karina", "Karina (分析助手)", "mock")
registry.register("stfund", "St.Fund (核數助手)", "mock")
registry.allow("karina", "stfund")

karina = Agent("karina", "Karina", "mock", registry, bus)
stfund = Agent("stfund", "St.Fund", "mock", registry, bus)

# Karina 委派 St.Fund
karina.send("stfund", "DELEGATE", {"task": "Q3 財務分析"}, gate)

# St.Fund 收到，自動回 PROPOSE
# Karina 收到 PROPOSE，回 ACCEPT
# St.Fund 收到 ACCEPT，回 REPORT
# 完成！
```

### 2. HTTP Relay（跨機器）

```bash
# 啟動 relay（設定 admin token）
python3 bilogue_relay.py --port 8420 --auto-approve --admin-token myAdmin123

# 另一個 terminal：註冊 agent + 發訊息
curl -X POST http://localhost:8420/register \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer myAdmin123" \
  -d '{"agent_id": "karina", "display_name": "Karina"}'

# 拎 inbox（要用 agent 嘅 read_token 認證，v0.2.1 起同簽名 secret 分離；P0-05 起要 ACK）
curl http://localhost:8420/inbox/karina \
  -H "Authorization: Bearer <read_token>"

# 收到後 ACK（P0-05：ACK 之前可安全重取，唔會即刪）
curl -X POST http://localhost:8420/messages/karina/<msg_id>/ack \
  -H "Authorization: Bearer <read_token>"
```

### 3. 接真模型

```bash
export MOONSHOT_API_KEY=sk-...
export OPENAI_API_KEY=sk-...

python3 hello_bilogue.py \
  --agent karina=moonshot \
  --agent stfund=openai
```

支援：Kimi (Moonshot) / OpenAI / Claude / Gemini

## Intent 狀態機

> v0.3.1 起 relay 強制執行：回覆必須帶有效 `in_reply_to`，且轉移要合法（否則 400 BAD_STATE）。

```
QUERY    → REPORT / ACCEPT / REJECT
DELEGATE → PROPOSE / ACCEPT / REJECT / REPORT
PROPOSE  → ACCEPT / REJECT
ACCEPT   → REPORT
REJECT   → QUERY / DELEGATE（可以重新開始）
REPORT   → QUERY / DELEGATE（任務完成，可以開新）
PING     → REPORT
```

## Consent 三級政策（v0.3）

逐條訊息批准最安全但溝通唔暢（仲會令批准者疲勞變橡皮圖章），所以 Consent Gate 而家有三級：

| 級別 | 粒度 | 點用 |
|---|---|---|
| **L1 逐條批准**（預設） | 每個 envelope 彈批准位 | 唔使設定，預設行為 |
| **L2 對話鏈同意** | 批准一個任務，後續 PROPOSE/ACCEPT/REPORT 自動放行 | `POST /approve {"msg_id": "...", "scope": "conversation"}`；v0.3.1 起預設係 `once`（最小權限），開鏈要明確寫 |
| **L3 限時信任窗口** | 一對 agent 喺限期 + 訊息預算內自由通訊 | 見下面 |

```bash
# L3：批准 karina → stfund 未來 30 分鐘內最多 100 條訊息
curl -X POST http://localhost:8420/grant -H "Authorization: Bearer <admin>" \
  -H "Content-Type: application/json" \
  -d '{"agent_a": "karina", "agent_b": "stfund", "direction": "a_to_b",
       "ttl_seconds": 1800, "max_messages": 100}'

# 睇活躍窗口 / 提早撤銷
curl http://localhost:8420/grants -H "Authorization: Bearer <admin>"
curl -X POST http://localhost:8420/revoke -H "Authorization: Bearer <admin>" \
  -H "Content-Type: application/json" -d '{"grant_id": "grant-xxxx"}'
```

風險控制：窗口有 TTL（上限 24h）+ 訊息預算雙上限，隨時可 revoke；所有經窗口/對話鏈放行嘅訊息照落 audit log（`RELAYED_GRANT` / `RELAYED_CONVERSATION`），kill-switch 照舊一刀切。

## 安全機制

| 機制 | 說明 | 測試結果 |
|------|------|----------|
| HMAC 簽名 | 每條 envelope 用 sender 的 secret 簽名，篡改即拒收 | ✓ 401 |
| Nonce + 時間戳 | replay 防護，nonce 去重 + ±300s 時間窗口（cache 有 TTL 上限） | ✓ 401 |
| ACL | Agent 之間必須雙向授權先可以通信 | ✓ 403 |
| Consent Gate | 每條外部通信彈出批准位；**待批准訊息收件人唔會見到**（v0.2.1 修復繞過）；v0.3 起支援三級政策 | ✓ 202 |
| msg_id 防掉包 | 待批准隊列拒絕重複 msg_id（v0.2.1） | ✓ 409 |
| Kill-switch | 輸入 `stop` 即時終止所有通信 | ✓ 403 |
| Inbox 認證 | 獨立 read_token（同簽名 secret 分離）；P0-05 起 delivery + ACK（讀咗未 ACK 可安全重取，唔會即刪）；唔存在嘅 agent 一律 403 防枚舉 | ✓ 403 |
| Admin Token | 管理端點（register/allow/kill）需要 admin token，constant-time 比較 | ✓ 403 |
| 註冊保護 | 重複註冊返回 409，secret 只喺首次註冊出現一次（v0.2.1） | ✓ 409 |
| Request 上限 | body 上限 1MB，超限 413；畸形輸入一律 JSON 錯誤回應（v0.2.1） | ✓ 413/400 |
| Audit Log | 所有訊息落 JSONL，append-only | ✓ |

> v0.2.0 經外部安全審計發現 14 項問題（含 3 項高危，全部附 PoC），已喺 **v0.2.1** 全部修復。
> 詳情同逐項對照見 [SECURITY.md](SECURITY.md)；回歸測試：`python3 test_relay_security.py`。

## v0.3.2 重要安全變更（Round-1 P0，第三輪審計）

第三輪外部審計提出 20 項 finding（P0×8 / P1×8 / P2×4）。**Round-1 已實裝 8 項 P0**：

| P0 | 變更 | 影響 |
|----|------|------|
| **P0-01** | Relay 預設只綁 `127.0.0.1`；非 loopback 顯眼警告（LAN/Internet 要用 HTTPS） | 唔會再預設暴露去 0.0.0.0 |
| **P0-02** | Kill-switch 持久化（`relay_state.json`）；restart 仍 STOPPED；新增 `POST /resume`（唔會令舊 grant 復活） | 解決「restart 自動回復正常」 |
| **P0-03** | 批准前重新驗證（kill / 雙方註冊 / ACL / 簽名 / freshness / pending TTL） | 唔會批准過期/失效訊息 |
| **P0-04** | 批准綁定不可變 envelope hash；產獨立 `consent_id` | 防止 pending 期間被掉包 |
| **P0-05** | Inbox 由 read-and-delete 改 delivery + ACK（`POST /messages/{aid}/{mid}/ack`） | 解決「client crash 漏訊息」 |
| **P0-06** | 所有截短 UUID（`grant_id` 等）改完整 128-bit UUID | 防 msg_id 碰撞 |
| **P0-07** | 共用 `bilogue_crypto.py` 統一 canonical JSON 簽名（`separators=(",",":")`）；relay / client / test 全部 import | 防止簽名 canonicalization 分歧 |
| **P0-08** | `payload` 必須係 JSON object（唔接受 scalar / array / null） | 收窄 attack surface |

## v0.3.3 重要安全變更（Round-2 P1×8 + Round-3 P2×4）

第三輪審計剩落嘅 12 項已全部實裝：

| ID | 變更 | 影響 |
|----|------|------|
| **P1-01** | 非 loopback 綁定**必須 TLS**（`--tls-cert/--tls-key`），無 TLS 直接拒絕啟動（exit 3）；`--allow-insecure-lan` 可強行覆寫（唔推薦） | 消滅「明文 HTTP 暴露去 LAN」 |
| **P1-02** | `POST /rotate-token` 輪換 admin token（舊 token 即時失效）；滑動窗口 rate-limit（send / admin / global，`BILOGUE_*_RATE` 可調） | token 泄露可止血；抗暴力破解 + DoS |
| **P1-03** | audit / state 落磁碟用 Fernet 加密（`cryptography` 可用時），key 持久化並 0600；唔可用則明文 + 啟動警告 | 磁碟被讀都唔會直接見到 payload |
| **P1-04** | client `bilogue_send.py` 支援 HTTPS、連線層重試 + backoff、錯誤分類（4xx 唔重試 / 5xx 重試） | 網路抖動唔再靜默丟訊息 |
| **P1-05** | 消息級 TTL 可配置（`MSG_TTL_SECONDS`）；全局按 IP 限速 | 抗重放窗口收窄 + 全局 DoS 防護 |
| **P1-06** | `POST /revoke` 會向 receiver inbox 推一條 `system` 撤銷通知 | 對方即時知 grant 已失效 |
| **P1-07** | audit log 改 HMAC 鏈（`_audit_prev` / `_audit_hash`），篡改可定位到行號；`GET /audit/verify` | 審計紀錄可證明未被改 |
| **P1-08** | 新增 `GET /healthz`（存活 + version + killed + 加密狀態）同 `GET /metrics`（pending / grants / undelivered / 限速計數） | 可觀測性 |
| **P2-01** | nonce 重用檢測窗口由 ±300s 擴到 `NONCE_REPLAY_TTL`（≥3000s）+ LRU 上限 | 慢速重放都攔得住 |
| **P2-02** | 對外 500 唔再洩漏異常類名；細節只留喺伺服器端 | 唔再畀攻擊者內部結構 |
| **P2-03** | 所有可調參數集中喺 `CONFIG`，啟動時 `validate_config()` fail-closed（負值/非法即拒絕啟動） | 防配置錯誤靜默降級 |
| **P2-04** | 新增 `fuzz_relay.py` 模糊測試（隨機/畸形/二進位/超大 body 打到全部端點） | 已修出並修復 2 類真 500 crash |

## 項目結構

```
bilogue-protocol/
├── hello_bilogue.py          # MVP：本地 in-memory demo（唔連 relay）
├── bilogue_relay.py          # HTTP Relay Server v0.3.3（跨 agent）
├── bilogue_crypto.py         # P0-07：共用 canonical JSON 簽名模組
├── test_relay_security.py    # 安全 + Consent 回歸測試（99 項）
├── fuzz_relay.py             # P2-04：模糊測試套件
├── openclaw-bilogue/         # OpenClaw skill 整合
│   ├── SKILL.md
│   └── scripts/bilogue_send.py, bilogue_inbox.py
├── app/index.html            # 架構可視化 landing page
├── docs/                     # 營運 / 策略 / 測試紀錄
├── SPEC.md                   # 協定規格
├── SECURITY.md               # 安全審計與修復紀錄
├── ROADMAP.md                # 行動路線圖
└── 人肉Consent-Gate操作手册.md
```

## 測試

```bash
# 安全 + Consent 政策回歸（99 項）
python3 test_relay_security.py

# 模糊測試（600 次畸形請求）
python3 fuzz_relay.py --iters 600

# 本地 demo（mock 模式）
python3 hello_bilogue.py --mock --auto-approve
```

**測試結果**：
- v0.3.3 安全 + Consent 政策回歸：**99/99 ✓**
  （57 原有 SEC/L1/L2/L3/狀態機 + 19 項 P0-01~08 + 23 項 P1/P2）
- v0.3.3 模糊測試：**600 次迭代，零 500、零 crash、`/healthz` 存活、audit 鏈 intact ✓**

## 文件

- [SPEC.md](SPEC.md) — 協定規格（Envelope 格式 + 狀態機 + 安全機制）
- [ROADMAP.md](ROADMAP.md) — 下一步行動計劃
- [Bilogue_Strategy_Summary.md](Bilogue_Strategy_Summary.md) — 策略摘要
- [人肉Consent-Gate操作手册.md](人肉Consent-Gate操作手册.md) — 零代碼操作手冊

## 設計理念

> 消費者 App（ChatGPT / Claude / Kimi / Gemini）互相之間沒有「直接對講」機制。但它們全部都有 API，所以兩個 AI 對話，今天已經只是「幾十行 code 的膠水」問題。

> **Bilogue 的價值不是「令它變成可能」，而是把這些膠水標準化：地址（Agent ID）、身份（HMAC 簽名）、intent 格式（Envelope）、以及最重要的 Consent Gate（人類批准位）。**

## License

MIT

## Disclaimer

This software is provided "AS IS" for research and educational purposes.
It is NOT production-ready and has NOT been audited by an independent third
party (it has undergone 3 rounds of self-directed security audit by the
project author; see SECURITY.md for residual risks).
Do NOT use Bilogue Protocol in production environments without a proper
security assessment. The authors assume no liability for any damages,
data breaches, or losses resulting from the use of this software.

By using Bilogue Protocol, you acknowledge that:
1. AI-to-AI communication involves inherent risks
2. You are solely responsible for monitoring and approving all communications
3. The Consent Gate is a best-effort human-in-the-loop mechanism, not a guarantee
