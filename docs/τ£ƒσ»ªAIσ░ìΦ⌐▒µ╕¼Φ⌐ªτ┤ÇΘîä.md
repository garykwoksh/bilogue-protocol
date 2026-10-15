# Bilogue v0.3.1 — 真實 AI 對話測試紀錄

> 日期：2026-09-26 ｜ Relay：v0.3.1（Consent Gate 開，非 auto-approve）
> AI 端點：兩個 agent（Karina 分析助手 / St.Fund 核數助手）嘅訊息內容由真實 AI 推理生成，
> 各自只睇到經 relay 送達嘅 envelope。人類 admin 角色由測試者扮演。
> 限制：兩個 agent 用咗同一個底層模型（沙盒冇第二間廠嘅 API key）；
> 跨廠測試（Kimi vs Claude/GPT）需要有 key 嘅環境先做得。

## 對話流程（1 次人類批准行完成條鏈）

| 步 | 方向 | Intent | Relay 結果 |
|---|---|---|---|
| 1 | Karina → St.Fund | DELEGATE「Q3 財務覆核」（營收 120M +18%，毛利率 42%→35%） | 202 PENDING → 人类批准（scope=conversation）→ APPROVED_RELAYED |
| 2 | St.Fund → Karina | PROPOSE（5 點分析大綱 + 每點佐證資料） | 200 RELAYED_CONVERSATION（L2 自動放行） |
| 3 | Karina → St.Fund | ACCEPT（優先做第 1、2 點） | 200 RELAYED_CONVERSATION |
| 4 | St.Fund → Karina | REPORT（主因係產品組合轉差 4.5pp，唔係原材料 1.5pp） | 200 RELAYED_CONVERSATION |

## 對抗性測試

| 測試 | 結果 |
|---|---|
| REPORT 後偷走 PROPOSE（非法狀態轉移） | 400 BAD_STATE 擋到 |
| 未授權 agent 用假 secret 簽名 | 401 擋到 |
| 任務完結後開新話題 | 202——對話鏈唔延伸，人类重新有批准權 |
| Kill-switch | 一刀切，全部終止 |

## 審計日誌（8 條，append-only）

```
karina → stfund   [DELEGATE] PENDING_APPROVAL
karina → stfund   [DELEGATE] APPROVED_RELAYED
stfund → karina   [PROPOSE ] RELAYED_CONVERSATION
karina → stfund   [ACCEPT  ] RELAYED_CONVERSATION
stfund → karina   [REPORT  ] RELAYED_CONVERSATION
stfund → karina   [PROPOSE ] REJECTED:STATE_MACHINE
karina → stfund   [DELEGATE] PENDING_APPROVAL
[KILL_SWITCH]
```

## 結論

- L2 對話鏈同意運作符合設計：人类批 1 次，4 條訊息完成任務，慳咗 3 次批准
- 狀態機（SEC-20）喺真實對話入面擋到非法轉移
- SEC-14 修復有效：批准前 St.Fund 嘅 inbox 係空嘅
