"""记忆抽取：把一批群消息变成「人物事实 + 会话摘要」。

一次模型调用产出两样东西——人物档案和会话摘要共用一次调用，
省 token 也省延迟。输出必须是 JSON，解析失败整批不处理（留待下轮重试）。
"""

import json

from bridge import llm

EXTRACT_SYSTEM = """你是记忆整理器。给你一批群聊记录，你要输出这个群里的人是谁、聊过什么。

只输出 JSON，不要任何解释、不要代码块围栏：
{"people": [{"speaker": "昵称", "bio": "一句话身份", "facts": ["事实1", "事实2"]}], "conv_summary": "这个群最近在聊什么，两三句"}

规则：
- 只记录记录里明确说到的信息，不推测、不补充常识。
- 闲聊寒暄、表情、无意义内容不记。
- 助手自己说的话不贡献人物事实，但可以进 conv_summary。
- 已有档案里没有的事实才写进 facts；facts 每条不超过 30 字，最多 5 条。
- bio 不超过 30 字；没有可写的信息就不要给这个人输出条目。
- conv_summary 写这个群的近期话题，不写具体的人名评价。
"""

MAX_PEOPLE = 20
FENCE = chr(96) * 3


def merge_facts(old, new) -> list:
    out = []
    for fact in list(old or []) + list(new or []):
        text = (fact or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def build_prompt(items: list, existing: list, summary: str) -> str:
    """待抽取的消息 + 已有档案 + 旧摘要 → 一段文本。"""
    lines = []
    for item in items or []:
        who = item.get("speaker") or "?"
        lines.append("[%s] %s: %s" % (item.get("ts") or "", who, item.get("text") or ""))
    known = []
    for person in existing or []:
        facts = person.get("facts") or []
        known.append("- %s：%s%s" % (
            person.get("speaker") or "",
            person.get("bio") or "",
            ("；" + "；".join(facts)) if facts else "",
        ))
    parts = ["【本批群聊记录】", "\n".join(lines)]
    if known:
        parts.append("【已有档案（只补新的事实，不要重复）】\n" + "\n".join(known))
    if summary:
        parts.append("【这个群此前的摘要】\n" + summary)
    return "\n\n".join(parts)


def parse_result(text: str) -> dict:
    """解析模型输出。容错：剥代码块围栏，取第一个 { 到最后一个 }。"""
    raw = (text or "").strip()
    if FENCE in raw:
        raw = raw.split(FENCE)[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("抽取结果里没有 JSON：%s" % raw[:200])
    return json.loads(raw[start:end + 1])


def extract(items: list, existing: list, summary: str, uin_of: dict) -> dict:
    """调模型做抽取。返回 {"people": [{speaker,bio,facts,uin}], "conv_summary": str}。"""
    prompt = build_prompt(items, existing, summary)
    text = llm.chat(EXTRACT_SYSTEM, [{"role": "user", "content": prompt}])
    data = parse_result(text)

    people = []
    for person in (data.get("people") or [])[:MAX_PEOPLE]:
        speaker = (person.get("speaker") or "").strip()
        if not speaker:
            continue
        raw_facts = person.get("facts") or []
        if isinstance(raw_facts, str):
            # 模型偶尔把 facts 写成一句话而不是数组——按字符拆会毁掉它
            raw_facts = [raw_facts]
        facts = [f.strip().lstrip("- ").strip()
                 for f in raw_facts if isinstance(f, str) and f.strip()]
        people.append({
            "speaker": speaker,
            "bio": (person.get("bio") or "").strip(),
            "facts": facts[:5],
            "uin": uin_of.get(speaker, ""),
        })
    return {"people": people, "conv_summary": (data.get("conv_summary") or "").strip()}
