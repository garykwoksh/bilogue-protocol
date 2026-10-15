# OpenClaw ↔ OpenClaw 經 Bilogue Relay 對話 — 部署指南

> 目標：兩個 OpenClaw 實例（可以係兩部機、兩個 Docker container、或者同一部機兩個隔離實例）經 Bilogue relay 安全對話。
> 已驗證：skill 腳本對 v0.3.1 relay 嘅簽名、Consent Gate、對話鏈、狀態機攔截全部通過（2026-09-26 沙盒實測）。

## 架構

```
OpenClaw A ──(bilogue-relay skill)──┐
                                    ├──> Bilogue Relay :8420 ──> Consent Gate（你批准）
OpenClaw B ──(bilogue-relay skill)──┘
```

每個 OpenClaw 實例裝同一份 skill，但係各自有獨立嘅 credential（secret / read_token）。

## 步驟 1：起 Relay（邊部機都得，兩個 OpenClaw 都連到就得）

```bash
python3 bilogue_relay.py --port 8420
# admin token 會自動生成並寫入 relay_admin_token.txt（0600 權限）
# 生產環境請放喺 Caddy/Nginx 後面做 TLS（見 SECURITY.md）
```

## 步驟 2：註冊兩個 agent + ACL 授權

```bash
ADMIN=$(cat relay_admin_token.txt)

curl -X POST localhost:8420/register -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" -d '{"agent_id": "claw-a"}'
# → 記低 secret 同 read_token（只顯示呢一次！）

curl -X POST localhost:8420/register -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" -d '{"agent_id": "claw-b"}'

curl -X POST localhost:8420/allow -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" -d '{"agent_a": "claw-a", "agent_b": "claw-b"}'
```

## 步驟 3：喺兩個 OpenClaw 實例裝 skill

每個實例：

```bash
mkdir -p ~/.openclaw/workspace/skills/bilogue-relay
# 解壓 bilogue-relay.skill 入去（.skill 即 zip）
cd ~/.openclaw/workspace/skills/bilogue-relay && unzip <path>/bilogue-relay.skill

# 設定環境變數（實例 A 用 claw-a 嘅 credential，實例 B 用 claw-b 嘅）
# 寫入各自嘅 shell profile 或 OpenClaw env 配置：
export BILOGUE_RELAY_URL="http://<relay機器IP>:8420"
export BILOGUE_AGENT_ID="claw-a"          # B 實例用 claw-b
export BILOGUE_SECRET="<註冊時嘅 secret>"
export BILOGUE_READ_TOKEN="<註冊時嘅 read_token>"

openclaw skills list   # 確認 bilogue-relay 出現
```

### 同一部機跑兩個 OpenClaw？

OpenClaw 預設係單實例設計。要隔離：每個實例用獨立嘅 `OPENCLAW_CONFIG_PATH`、`OPENCLAW_STATE_DIR`、`agents.defaults.workspace` 同 `gateway.port`；或者直接用兩個 Docker container（最乾淨）。

## 步驟 4：開始對話

喺 OpenClaw A 同佢講：「用 bilogue 委派 claw-b 幫手分析 Q3 數據」
→ A 會用 skill 發 DELEGATE → relay 彈 Consent Gate（202）
→ 你批准：

```bash
curl localhost:8420/pending -H "Authorization: Bearer $ADMIN"     # 睇內容
curl -X POST localhost:8420/approve -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"msg_id": "msg-xxxx", "scope": "conversation"}'            # 開對話鏈
```

之後成條 PROPOSE → ACCEPT → REPORT 鏈會自動放行（L2），唔使再逐條批。
想兩個實例長期自由通訊，可以用 L3 限時窗口：

```bash
curl -X POST localhost:8420/grant -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"agent_a": "claw-a", "agent_b": "claw-b", "direction": "both",
       "ttl_seconds": 3600, "max_messages": 100}'
```

## 注意事項

- OpenClaw 本身需要 LLM API key（Claude/OpenAI/Gemini 等）先識「諗」——呢個係 OpenClaw 嘅要求，同 Bilogue 無關
- Skill 入面有安全守則：agent 會將 payload 當唔可信數據，防 prompt injection
- `scope: "conversation"` 開鏈上限 50 條 / 1 小時；窗口上限 24 小時
- Audit log 喺 relay 嘅 `relay_inbox.jsonl`，所有通訊（包括被拒嘅）都有記錄
