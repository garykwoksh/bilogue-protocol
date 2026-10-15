# 人肉 Consent Gate 操作手冊（零代碼版 hello-bilogue）

> 目的：唔使寫 code，用兩個 AI 嘅網頁版，親身體驗一次「AI 對 AI 通信 + 人類批准」。
> 你扮演嘅角色：**Message Bus ＋ Consent Gate ＋ Kill-switch**——即係 Bilogue 嘅人肉原型。

---

## 0. 你需要嘅嘢

- 兩個 AI 嘅 chat 視窗（邊個都得：ChatGPT、Claude、Kimi、Gemini……）
- 呢份手冊入面嘅「開機指令」同「訊息格式」
- 10–15 分鐘

以下用 **Karina（通用助手）** 同 **St.Fund（金融助手）** 做例子，你換名就得。

---

## 1. 開機：將身份植入每個 AI

喺每個 AI 嘅 chat 開頭，貼入佢專屬嘅開機指令。

**Karina 視窗貼：**

```text
你係 Karina，一個通用 AI 助手，Agent ID 係 karina@g-k.ai。
你而家接入咗 Bilogue 網絡，可以同其他 agent 通信。
規矩：
1. 所有對外通信必須用指定 Intent Envelope 格式（我會提供），唔好用普通說話。
2. 你唔可以直接聯絡其他 agent——所有訊息由我（人類）轉發。
3. 收到任務時，如果超出你嘅能力範圍（例如金融分析），用 DELEGATE 意圖交畀合適嘅 agent。
4. 收到 PROPOSE 時，你可以 ACCEPT 或 REJECT。
5. 每次回覆只輸出一個 Intent Envelope，唔好加其他文字。
```

**St.Fund 視窗貼：**

```text
你係 St.Fund，一個金融分析 AI 助手，Agent ID 係 st.fund@g-k.ai。
你而家接入咗 Bilogue 網絡，可以同其他 agent 通信。
規矩：
1. 所有對外通信必須用指定 Intent Envelope 格式（我會提供），唔好用普通說話。
2. 你唔可以直接聯絡其他 agent——所有訊息由我（人類）轉發。
3. 收到 DELEGATE 時，用 PROPOSE 提出執行方案；收到 ACCEPT 先好執行，然後用 REPORT 交返結果。
4. 每次回覆只輸出一個 Intent Envelope，唔好加其他文字。
```

**兩邊都貼嘅格式定義：**

```text
Intent Envelope 格式（JSON）：
{
  "sender": "<你嘅 Agent ID>",
  "receiver": "<對方嘅 Agent ID>",
  "intent_type": "QUERY | DELEGATE | PROPOSE | ACCEPT | REJECT | REPORT",
  "payload": "<內容>",
  "consent_ref": "需要批准時留空，批准後由人類填入"
}
```

---

## 2. ACL：你嘅電話簿（開波前定好）

寫低邊對 agent 可以免批通信、邊啲必批。第一版建議全部必批：

| 通信方向 | 級別 | 你要做嘅嘢 |
|---|---|---|
| Karina ↔ St.Fund | External（必批） | 每個 envelope 你睇過先轉發 |
| 任何 agent → 陌生 agent | External（必批＋問貴價問題） | 佢點知對方存在？想做咩？ |

---

## 3. Consent Gate：每次轉發前嘅三問

每收到一個 envelope，轉發之前問自己：

1. **邊個發？** sender 係咪佢聲稱嘅嗰個？（人肉版：你記得邊個視窗出嘅）
2. **做咩？** intent_type 同 payload 合唔合理？DELEGATE 嘅任務係咪你都想佢做？
3. **批唔批？** 批 → 喺 `consent_ref` 填一個編號（例如 `C-001`）先轉發；唔批 → 喺原視窗回 `REJECT`。

**Kill-switch**：任何時候覺得唔對路，喺兩邊視窗同時輸入 `STOP ALL`，今次實驗即停。記低係咩觸發你撳——嗰個就係規格要處理嘅風險。

---

## 4. 示範劇本：一次完整通話

**Step 1 — 你喺 Karina 視窗落任務：**

```text
任務：我想要一份「2026 年 AI 基礎設施投資趨勢」嘅一頁紙摘要。
你呢個任務應該點處理，用 Intent Envelope 答我。
```

預期 Karina 輸出類似：

```json
{
  "sender": "karina@g-k.ai",
  "receiver": "st.fund@g-k.ai",
  "intent_type": "DELEGATE",
  "payload": "請分析 2026 年 AI 基礎設施投資趨勢，重點：融資額、主要玩家、風險。需要一頁紙摘要。",
  "consent_ref": ""
}
```

**Step 2 — 你做 Consent Gate**：三問過關 → 填 `consent_ref: "C-001"` → 貼去 St.Fund 視窗。

**Step 3 — St.Fund 應該回 PROPOSE：**

```json
{
  "sender": "st.fund@g-k.ai",
  "receiver": "karina@g-k.ai",
  "intent_type": "PROPOSE",
  "payload": "方案：1) 列出 2026 上半年主要融資事件 2) 歸納三個趨勢 3) 一段風險提示。預計 300 字。接受請回 ACCEPT。",
  "consent_ref": ""
}
```

**Step 4 — 你批准，填 `C-002`，轉發返 Karina** → Karina 回 `ACCEPT` → 你批 `C-003` 轉發返 St.Fund。

**Step 5 — St.Fund 執行，回 REPORT（任務結果）** → 你批 `C-004` 轉發返 Karina → Karina 用最終結果答你。

流程圖：

```text
你 ──任務──▶ Karina ──DELEGATE──▶ [你: Consent Gate] ──▶ St.Fund
你 ◀──結果── Karina ◀──REPORT──── [你: Consent Gate] ◀── St.Fund
                   （PROPOSE / ACCEPT 來回同樣要批）
```

---

## 5. 觀察清單：甩辘位先係寶藏

試完記低以下嘢——每一條都係 SPEC.md v0.1 嘅輸入：

- [ ] AI 有冇跟唔到 envelope 格式、加咗廢話？（→ 格式約束要寫幾硬）
- [ ] 有冇 AI 「作嘢」話收到訊息但其實冇？（→ 需要 message ID ＋ 簽名驗證）
- [ ] PROPOSE → ACCEPT 來回嫌唔嫌多？（→ 邊啲意圖應該免批）
- [ ] 你批咗幾多次？煩唔煩？（→ consent token 應該點設計有效期）
- [ ] 有冇一刻你想撳 STOP ALL？係咩觸發？（→ kill-switch 嘅觸發條件）
- [ ] 換一個 AI 做同一角色，行為差幾遠？（→ 協議要跨廠商中立）

---

## 6. 玩完之後

呢個人肉版本做到嘅嘢，就係 `hello_bilogue.py` 自動化嘅嘢——message bus、簽名驗證、consent gate、kill-switch 全部齊。跑過人肉版再跑 code 版，你會好清楚每一行 code 代替咗你邊個動作。

*Bilogue, first proposed by G K et al., 2026*
