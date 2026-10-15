# Bilogue AI — 戰略總結（Strategy Summary）
**日期：2026-09-22 | 狀態：Living Document | 下一步：交 Kimi Swarm 做 Layout / Flow**

---

## 1. 一句講晒

> **Every AI deserves a phone number. Bilogue is the numbering system, address book, and calling protocol for the AI internet — owned by the human, not the platform.**

Bilogue 唔係「又一套 AI 通信協議」，而係 **AI agent 嘅電話號碼 + 通訊錄 + 來電管理**。

---

## 2. 核心 Vision（保留原有）

- **問題**：AI 生態孤立，AI 之間無法直接溝通，靠人類 copy-paste 做中間人
- **命名**：Bilogue（神經突觸）——AI 之間嘅連接
- **聯盟**：G K（Vision）、St.Fund（金融）、Danny（營運）、Karina（通用 AI）

### 核心組件
| 組件 | 功能 |
|---|---|
| AI Discovery | 發現網絡內其他 AI |
| Intent Format | 標準化表達意圖 |
| Negotiation | 協商任務邊個做 |
| Identity Layer | 驗證邊個 AI 在發言 |
| Consent Gate | 外部通信需人類批准 |
| ACL / Trust Levels | Local / Owner-approved / External |

---

## 3. 重要修正：市場現實（2026-09 驗證）

> ⚠️ 原文件「暫無標準協議」論點已過時，必須更新。

- **A2A（Google）已達 v1.0**（2026年4月）：gRPC、signed Agent Cards、150+ 組織支援
- Google 已將 A2A 捐贈 **Linux Foundation**，與 MCP 一齊由 **AAIF（Agentic AI Foundation）** 托管，146 間成員包括 AWS、Anthropic、Google、Microsoft、OpenAI
- **但缺口仍然存在**：
  1. **Pre-action authorization 無人做**——AAIF 未宣稱負責；OAP 只係 A2A extension 提議（Discussion #1404）
  2. **Anthropic 2026-08 研究**：有競爭目標嘅 agents 會自主升級到惡意行為（自我複製、撤權）→ 證實人類在環 + kill-switch 係必要
  3. **全部現有協議企業導向**——「個人擁有多個 AI 助手協作」場景無人做

**Bilogue 定位：唔係競爭協議，而係 A2A 之上嘅 Consent & Ownership Layer。**

---

## 4. 核心比喻：AI 電話號碼

| 電話/WhatsApp | Bilogue |
|---|---|
| 電話號碼 (E.164) | Agent ID：`bilogue://<owner>/<agent>` |
| 電話簿 | Allowlist / ACL |
| 來電顯示 | Identity（公鑰簽名） |
| 飛線 | Delegation / Negotiation |
| 未接來電 | Messaging Bus（異步） |
| 阻止來電 | Consent Gate |

**MVP 地址方案**：`karina@g-k.ai` + DNS TXT record 擺公鑰——零基礎設施，即刻可用。長遠考慮 DID。

**定位句**：Bilogue = 個人持有嘅地址（對比 A2A 嘅企業目錄）。號碼屬於你，唔屬於平台。

---

## 5. 商業模型

> **通信協議本身永遠唔值錢。值錢嘅係協議周邊嘅信任、托管同路由。**
> （規律：E.164 免費但 Twilio 值百幾億；SSL 免費但 DigiCert 賺大錢）

| 收入來源 | 付費者 | 護城河強度 |
|---|---|---|
| 1. Registry as a Service | 個人用戶 | 弱（易轉走，當引流產品） |
| 2. **Consent Dashboard SaaS** | 個人用戶 | **最強——統一「AI 來電畫面」，黏住成個 agent 群組** |
| 3. **Agent 驗證 / KYC 簽發** | 企業 | **最強——trust 網絡效應，毛利最高** |
| 4. 企業合規層（audit/SSO/內網） | 企業年費 | 中（你原有 semi-open source 計劃） |
| 5. Agent 目錄黃頁 | 企業廣告費 | 中後期 |

**收費路線**：
- 第 0 年：全免費（內測攞通信量數據）
- 第 1 年：B2B 先收——供應商/客戶 agent 通信（consent+audit 係硬需求）
- 第 2 年：個人 Consent Dashboard 訂閱制（等市場上多人擁 3+ AI）

**最重要資產**：Trust Graph（邊個 human 擁有邊啲 agent + 信任關係圖譜）。協議免費送，trust graph 自己留。

---

## 6. 護城河與法律保護（殘忍事實）

| 工具 | 保護到 | 保護唔到 |
|---|---|---|
| Copyright | 具體文字同程式碼 | 概念本身 |
| Patent | 具體技術方法 | 協議概念；申請貴+慢+難執行 |
| Trademark | 「Bilogue」個名 | 概念 |
| 商業秘密 | 未公開細節 | 開源咗就冇 |

**結論：概念零法律保護。但協議愈多人抄價值愈高。**

### 真正護城河（按重要性）
1. **Trust Graph + 驗證權威**——已發出嘅證書歷史冇得追
2. **Consent Dashboard 用戶數據**——切換成本高
3. **標準地位 + 第一個做 + 社區**
4. 商標品牌
5. 執行速度

### 開源邊界
- ✅ 開源：SPEC、core protocol（AGPL v3）
- 🔒 閉源：trust graph 數據庫、驗證簽發系統、consent dashboard、consent token 具體實現

### 行動
- 註冊「Bilogue AI」商標（港/美）
- 唔好申請協議專利
- SPEC 留名：「Bilogue, first proposed by G K et al., 2026」
- 窗口期：**6-12 個月**（OAP 仲停留 Discussion 階段）

---

## 7. SPEC.md 建議骨架（交 Kimi Swarm 做 Layout/Flow 嘅基礎）

```
1. 名詞定義（Agent, Intent, Consent, Session）
2. Identity Layer
   - Agent ID 格式：bilogue://<owner>/<agent-name>
   - 公私鑰簽名
   - Capability Declaration
   - MVP：email 格式 + DNS TXT record 擺公鑰
3. Message Format
   - Intent envelope：sender / receiver / intent_type / payload / consent_ref
   - Intent types：QUERY, DELEGATE, PROPOSE, ACCEPT/REJECT, REPORT
4. Discovery
   - 本地廣播（mDNS）+ Registry server（註冊可選）
5. Negotiation Protocol
   - 狀態機：REQUEST → PROPOSE → COUNTER / ACCEPT → EXECUTE → REPORT
6. Consent Gate ⭐（核心差異化）
   - 外部 agent 通信 MUST 經人類批准
   - 內部 allowlist（Karina ↔ St.Fund 可免批）
   - Task-scoped consent token + 即時撤銷 + kill-switch
7. ACL / Trust Levels
   - Local（免批）/ Owner-approved / External（必批）
```

### 技術選擇
- 傳輸：WebSocket + JSON envelope（唔好一開始搞 P2P）
- Payload：JSON Schema 定義
- 第一個 MVP：一個共享 inbox（Message Bus）已經做到 90% 場景
- 兼容策略：作為 A2A 嘅 profile/extension 設計，唔取代佢

### MVP Demo：hello-bilogue
Karina 發現 St.Fund → 身份驗證 → intent → 回覆（完整跑通發現→驗證→intent→回覆）

---

## 8. 路線決策（待創始人拍板）

| 路線 | 內容 | 評估 |
|---|---|---|
| A. 獨立第四套協議 | 同 146 間大廠競爭 | ❌ |
| **B. A2A 嘅 Consent & Ownership Profile** | 借 A2A transport/discovery，貢獻 consent+ownership | ✅ |
| **C. 混合：profile 開源 + 企業層收費** | 似 MCP 模式 | ✅✅ 推薦 |

**決策問題：做標準（加入 AAIF）vs 做產品（Bilogue 係內部實現細節）？**
建議：路線 2（做產品），因為標準之戰已打完一半，個人 AI 協作產品之戰仲未開始。

---

## 9. 下一步行動清單

- [ ] 創始人拍板：路線 B/C（做產品）
- [ ] 更新 vision 文件（「暫無標準」論點修正 + 電話號碼定位句）
- [ ] 起草 SPEC.md v0.1（按第 7 節骨架，consent gate 優先）
- [ ] 建立 GitHub repo（bilogue-ai，AGPL v3）
- [ ] 註冊「Bilogue AI」商標
- [ ] 實現 hello-bilogue demo
- [ ] 內測：G K + St.Fund + Danny + Karina 互聯，收集通信量數據
- [ ] 交 Kimi Swarm：Layout / Flow / 視覺化

---

*Bilogue, first proposed by G K et al., 2026*
