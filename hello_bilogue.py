#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hello-bilogue — AI 對 AI 通信最小可行 demo（Bilogue MVP）

跑通完整鏈路：發現 → 身份驗證（HMAC 簽名）→ Intent → Consent Gate（人類批准）→ 回覆

用法：
  # 冇 API key：mock 模式，即刻睇到完整流程
  python3 hello_bilogue.py --mock --auto-approve

  # 有 API key：接真模型（env 讀 key）
  export MOONSHOT_API_KEY=sk-...      # Kimi
  export OPENAI_API_KEY=sk-...        # OpenAI
  export ANTHROPIC_API_KEY=sk-...     # Claude
  export GEMINI_API_KEY=...           # Gemini
  python3 hello_bilogue.py --agent karina=moonshot --agent stfund=openai

  # 互動批准（唔加 --auto-approve）：每個外部通信你要撳 y/n，輸入 stop 即 kill-switch
  python3 hello_bilogue.py --mock

純標準庫，唔使 pip install。
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import uuid

# ---------------------------------------------------------------- 訊息格式

INTENT_TYPES = ["QUERY", "DELEGATE", "PROPOSE", "ACCEPT", "REJECT", "REPORT"]

# 玩具版身份層：每個 agent 一條共享密鑰做 HMAC 簽名。
# 正式版係公私鑰（SPEC 第 2 節：MVP 用 DNS TXT record 擺公鑰）。
# 安全提示：呢度嘅 secret 只係 demo 用，正式部署要由環境變數注入。
import secrets as _secrets
def _gen_demo_secret(agent_id):
    """demo 用：隨機生成 32 位 hex secret（唔用硬編碼值）。"""
    return hashlib.sha256(
        f"{agent_id}:{_secrets.token_hex(16)}".encode()
    ).hexdigest()[:32]

AGENT_SECRETS = {
    "karina@g-k.ai": os.environ.get("Bilogue_KARINA_SECRET") or _gen_demo_secret("karina"),
    "st.fund@g-k.ai": os.environ.get("Bilogue_STFUND_SECRET") or _gen_demo_secret("stfund"),
    "danny@g-k.ai": os.environ.get("Bilogue_DANNY_SECRET") or _gen_demo_secret("danny"),
}


def sign(envelope_fields: dict, secret: str) -> str:
    # P0-07: 用同 relay 一致嘅 canonical JSON（separators=(",",":")）
    canonical = json.dumps(envelope_fields, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def make_envelope(sender, receiver, intent_type, payload, consent_ref=""):
    body = {
        "id": "msg-" + uuid.uuid4().hex,  # P0-06: full UUID
        "ts": int(time.time()),
        "sender": sender,
        "receiver": receiver,
        "intent_type": intent_type,
        "payload": payload,
        "consent_ref": consent_ref,
    }
    secret = AGENT_SECRETS.get(sender)
    if not secret:
        raise ValueError(f"未知 sender（未註冊嘅 agent）：{sender}")
    body["sig"] = sign(body, secret)
    return body


def verify(env: dict) -> bool:
    secret = AGENT_SECRETS.get(env.get("sender", ""))
    if not secret:
        return False
    fields = {k: v for k, v in env.items() if k != "sig"}
    return hmac.compare_digest(sign(fields, secret), env.get("sig", ""))


# ---------------------------------------------------------------- Message Bus

class Bus:
    """共享 inbox：所有訊息落 JSONL，人類可以隨時打開睇（audit 嘅雛形）。"""

    def __init__(self, path="bilogue_inbox.jsonl"):
        self.path = path
        open(self.path, "a", encoding="utf-8").close()

    def post(self, env: dict):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(env, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- Consent Gate

# ACL：allowlist 內嘅方向免批（Owner-approved），其餘必批（External）
ALLOWLIST = set()  # 例：{("karina@g-k.ai", "st.fund@g-k.ai")} 加入即免批


class ConsentGate:
    """核心差異化：外部通信 MUST 經人類批准。輸入 stop = kill-switch。"""

    def __init__(self, auto=False):
        self.auto = auto
        self.counter = 0
        self.killed = False

    def check(self, env: dict) -> bool:
        pair = (env["sender"], env["receiver"])
        if pair in ALLOWLIST:
            print(f"  [Gate] {pair[0]} → {pair[1]} 喺 allowlist，免批放行")
            return True
        self.counter += 1
        ref = f"C-{self.counter:03d}"
        env["consent_ref"] = ref
        print("\n  ┌─ Consent Gate ─────────────────────────────")
        print(f"  │ 來電：{env['sender']}")
        print(f"  │ 想搵：{env['receiver']}")
        print(f"  │ 意圖：{env['intent_type']}")
        payload_preview = env["payload"] if len(env["payload"]) <= 200 else env["payload"][:200] + "…"
        print(f"  │ 內容：{payload_preview}")
        if self.auto:
            print(f"  │ （auto-approve）批准 → {ref}")
            print("  └─────────────────────────────────────────────")
            return True
        while True:
            ans = input(f"  │ 批准？ [y] 批准 / [n] 拒絕 / [stop] 全部終止：").strip().lower()
            if ans in ("y", "yes"):
                print(f"  │ 已批准 → {ref}")
                print("  └─────────────────────────────────────────────")
                return True
            if ans in ("n", "no"):
                print("  │ 已拒絕")
                print("  └─────────────────────────────────────────────")
                return False
            if ans == "stop":
                self.killed = True
                print("  │ ⛔ KILL-SWITCH 觸發：所有通信即時終止")
                print("  └─────────────────────────────────────────────")
                return False
            print("  │ 請輸入 y / n / stop")


# ---------------------------------------------------------------- LLM 接駁

def _post_json(url, headers, payload, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def llm_chat(provider: str, model: str, system: str, user: str) -> str:
    """跨廠商統一入口。協議要中立，接駁層就係咁簡單。"""
    if provider in ("openai", "moonshot"):
        key_env = "OPENAI_API_KEY" if provider == "openai" else "MOONSHOT_API_KEY"
        base = "https://api.openai.com/v1" if provider == "openai" else "https://api.moonshot.cn/v1"
        key = os.environ.get(key_env)
        if not key:
            raise RuntimeError(f"未設定 {key_env}")
        data = _post_json(
            base + "/chat/completions",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            {"model": model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}],
             "temperature": 0.4},
        )
        return data["choices"][0]["message"]["content"]
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("未設定 ANTHROPIC_API_KEY")
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01",
             "Content-Type": "application/json"},
            {"model": model, "max_tokens": 1500, "system": system,
             "messages": [{"role": "user", "content": user}]},
        )
        return "".join(b.get("text", "") for b in data["content"])
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("未設定 GEMINI_API_KEY")
        data = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            {"Content-Type": "application/json"},
            {"system_instruction": {"parts": [{"text": system}]},
             "contents": [{"role": "user", "parts": [{"text": user}]}]},
        )
        return data["candidates"][0]["content"]["parts"][0]["text"]
    raise ValueError(f"未知 provider：{provider}")


DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "moonshot": "moonshot-v1-8k",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-2.0-flash",
}


# ---------------------------------------------------------------- Agent

PERSONA = {
    "karina@g-k.ai": (
        "你係 Karina，通用 AI 助手。收到任務時，金融分析類工作要 DELEGATE 畀 "
        "st.fund@g-k.ai；收到 PROPOSE 回 ACCEPT；收到 REPORT 後用 100 字內總結畀人類。"
        "只輸出 JSON envelope，唔好加其他文字。"
    ),
    "st.fund@g-k.ai": (
        "你係 St.Fund，金融分析助手。收到 DELEGATE 用 PROPOSE 出方案（3 步內）；"
        "收到 ACCEPT 先執行，然後 REPORT 交結果（300 字內）。"
        "只輸出 JSON envelope，唔好加其他文字。"
    ),
}

# mock 模式嘅罐頭行為：唔使 API 都可以示範完整狀態機
MOCK_SCRIPT = {
    ("karina@g-k.ai", "TASK"): {
        "receiver": "st.fund@g-k.ai", "intent_type": "DELEGATE",
        "payload": "請分析 2026 年 AI 基礎設施投資趨勢：主要融資事件、三個趨勢、一段風險提示，300 字內。",
    },
    ("st.fund@g-k.ai", "DELEGATE"): {
        "receiver": "karina@g-k.ai", "intent_type": "PROPOSE",
        "payload": "方案：1) 盤點 2026 上半年主要融資 2) 歸納算力/能源/agent 基建三條主線 3) 風險一段。300 字內。接受請回 ACCEPT。",
    },
    ("karina@g-k.ai", "PROPOSE"): {
        "receiver": "st.fund@g-k.ai", "intent_type": "ACCEPT",
        "payload": "方案可以，照做。",
    },
    ("st.fund@g-k.ai", "ACCEPT"): {
        "receiver": "karina@g-k.ai", "intent_type": "REPORT",
        "payload": "【REPORT】2026 AI 基建投資趨勢：資金集中喺算力供應鏈（GPU 租賃、液冷數據中心）、能源配套（核能 PPA）、同 agentic 基建（協議、身份、托管）。三條主線：算力商品化、能源即護城河、agent 互聯標準化。風險：算力過剩回調、監管對跨境算力嘅限制、協議標準之戰嘅站隊風險。",
    },
}


class Agent:
    def __init__(self, agent_id, provider="mock", model=None):
        self.id = agent_id
        self.provider = provider
        self.model = model or DEFAULT_MODEL.get(provider, "")

    def respond(self, trigger: str, incoming_payload: str) -> dict:
        """trigger：TASK（人類落單）或收到嘅 intent_type。回傳 envelope 半成品。"""
        if self.provider == "mock":
            return MOCK_SCRIPT[(self.id, trigger)]
        system = PERSONA[self.id] + (
            "\nEnvelope 格式：{\"sender\": \"%s\", \"receiver\": \"<對方>\", "
            "\"intent_type\": \"QUERY|DELEGATE|PROPOSE|ACCEPT|REJECT|REPORT\", "
            "\"payload\": \"<內容>\"}。只輸出呢個 JSON。" % self.id
        )
        if trigger == "TASK":
            user = f"人類任務：{incoming_payload}"
        else:
            user = f"收到 {trigger}：{incoming_payload}"
        raw = llm_chat(self.provider, self.model, system, user)
        return _parse_envelope(raw)


def _parse_envelope(raw: str) -> dict:
    """真模型成日加 ```json 圍欄或廢話——呢度係協議要處理嘅現實。"""
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start:end + 1])
    return {
        "receiver": data["receiver"],
        "intent_type": data["intent_type"].upper(),
        "payload": str(data["payload"]),
    }


# ---------------------------------------------------------------- 主流程

def route(bus, gate, env) -> bool:
    """一個 envelope 嘅完整生命週期：驗簽名 → Gate → 落 bus。"""
    print(f"\n◆ {env['sender']} ──{env['intent_type']}──▶ {env['receiver']}")
    if env["intent_type"] not in INTENT_TYPES:
        print("  [Bus] ✗ 未知 intent_type，丟棄")
        return False
    if not verify(env):
        print("  [Bus] ✗ 簽名驗證失敗——身份存疑，丟棄（呢下就係 Identity Layer）")
        return False
    print("  [Bus] ✓ 簽名驗證通過")
    if not gate.check(env):
        return False
    bus.post(env)
    print("  [Bus] ✓ 已送達 inbox")
    return True


def run(task, agents_cfg, auto_approve):
    bus = Bus()
    gate = ConsentGate(auto=auto_approve)
    agents = {
        aid: Agent(aid, cfg[0], cfg[1]) for aid, cfg in agents_cfg.items()
    }

    print("=" * 60)
    print("hello-bilogue · MVP demo")
    print("網絡成員（Discovery 完成）：", "、".join(agents))
    print("=" * 60)

    karina = agents["karina@g-k.ai"]
    stfund = agents["st.fund@g-k.ai"]

    # 1) 人類落任務 → Karina 決定 DELEGATE
    print(f"\n[人類] 任務：{task}")
    out = karina.respond("TASK", task)
    env = make_envelope(karina.id, out["receiver"], out["intent_type"], out["payload"])
    if not route(bus, gate, env) or gate.killed:
        return _shutdown(gate)

    # 2) St.Fund 收到 DELEGATE → PROPOSE
    out = stfund.respond("DELEGATE", env["payload"])
    env = make_envelope(stfund.id, out["receiver"], out["intent_type"], out["payload"])
    if not route(bus, gate, env) or gate.killed:
        return _shutdown(gate)

    # 3) Karina 收到 PROPOSE → ACCEPT / REJECT
    out = karina.respond("PROPOSE", env["payload"])
    env = make_envelope(karina.id, out["receiver"], out["intent_type"], out["payload"])
    if not route(bus, gate, env) or gate.killed:
        return _shutdown(gate)
    if env["intent_type"] == "REJECT":
        print("\n[結果] Karina 拒絕咗方案，流程結束。")
        return _shutdown(gate)

    # 4) St.Fund 收到 ACCEPT → 執行 → REPORT
    out = stfund.respond("ACCEPT", env["payload"])
    env = make_envelope(stfund.id, out["receiver"], out["intent_type"], out["payload"])
    if not route(bus, gate, env) or gate.killed:
        return _shutdown(gate)

    # 5) Karina 總結畀人類
    print("\n" + "=" * 60)
    print("[Karina → 人類] 最終回覆：")
    print(env["payload"])
    print("=" * 60)
    print(f"\n完整通信紀錄（audit log）：bilogue_inbox.jsonl，共 {gate.counter} 次人工批准")
    print("流程跑通：發現 → 驗證 → DELEGATE → PROPOSE → ACCEPT → REPORT ✓")


def _shutdown(gate):
    if gate.killed:
        print("\n[系統] Kill-switch 已觸發，所有 agent 通信終止。inbox 紀錄已保留供審計。")
    else:
        print("\n[系統] 流程被 Consent Gate 拒絕而終止。")


def main():
    p = argparse.ArgumentParser(description="hello-bilogue MVP demo")
    p.add_argument("--mock", action="store_true", help="全部 agent 用 mock（唔使 API key）")
    p.add_argument("--agent", action="append", default=[],
                   help="格式 名=provider 或 名=provider:model，例如 karina=moonshot stfund=openai:gpt-4o-mini")
    p.add_argument("--auto-approve", action="store_true", help="Consent Gate 自動批准（示範用）")
    p.add_argument("--task", default="我想要一份「2026 年 AI 基礎設施投資趨勢」嘅一頁紙摘要。")
    args = p.parse_args()

    cfg = {"karina@g-k.ai": ("mock", None), "st.fund@g-k.ai": ("mock", None)}
    if not args.mock:
        for spec in args.agent:
            name, _, prov = spec.partition("=")
            provider, _, model = prov.partition(":")
            full = f"{name}@g-k.ai"
            if full not in cfg:
                sys.exit(f"未知 agent 名：{name}（可用：karina、stfund）")
            cfg[full] = (provider, model or None)
    run(args.task, cfg, args.auto_approve)


if __name__ == "__main__":
    main()
