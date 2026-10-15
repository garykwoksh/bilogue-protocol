# Contributing to Bilogue Protocol

多謝你考慮貢獻 Bilogue！呢個項目而家由一兩個人維護，所以你嘅參與好重要。以下係啲基本規矩，令 PR 過得順暢。

## 開始之前

- Bilogue 係 **純標準庫 Python 3.8+**，唔使 `pip install` 任何嘢就可以跑。
- 先跑一次測試，確認你嘅環境正常：
  ```bash
  python3 test_relay_security.py   # 應該 57 passed, 0 failed
  ```

## 提 Issue

- **Bug report**：用 `.github/ISSUE_TEMPLATE/bug_report.md`，附重現步驟 + 預期/實際結果 + relay 版本。
- **Feature request**：講清楚用例（你點解需要呢個功能），唔好一開始就講實作。
- **安全漏洞**：**唔好開 public issue**。睇 [SECURITY.md](SECURITY.md)，私下回報。

## 提 Pull Request

1. Fork → 開 branch（`fix-sec-xx-描述` / `feat-描述`）
2. **改代碼之前**，先確認有對應嘅 issue 或者講清楚你點解要改
3. 跑測試，確保 57/57 仍然通過：
   ```bash
   python3 test_relay_security.py
   ```
4. 如果你加新功能 / 新安全機制，**要補測試**（改 `test_relay_security.py` 或新增測試檔）
5. Commit message 風格：
   - `fix(sec-21): 描述` — 安全修復
   - `feat: 描述` — 新功能
   - `docs: 描述` — 文件
   - `test: 描述` — 測試
6. PR description 講：改咗咩、點解改、測試結果

## 安全相關 PR 嘅額外要求

- 每個安全修復要喺 `SECURITY.md` 開一個 SEC-XX entry（severity + issue + fix）
- 對應嘅回歸測試要喺 `test_relay_security.py` 入面，命名清晰（`SEC-XX: 描述`）
- 唔好喺 commit message、PR description、測試入面放真實嘅 secret / token

## 風格

- 用 4 空格縮進
- docstring + 註解用廣東話 / 英文都得，但 API contract（端點、欄位名）保持英文
- 一個檔案一個職責；純標準庫優先，引入第三方依賴要喺 PR 講清楚理由

## 行為準則

參與呢個項目即係同意遵守 [Code of Conduct](CODE_OF_CONDUCT.md)。

---

*Bilogue, first proposed by G K et al., 2026*