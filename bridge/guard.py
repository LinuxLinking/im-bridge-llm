"""发言闸门：判断一条消息值不值得回、该不该回避。

纯函数 + 配置驱动：词表都在 .env 里，随时可增删，不用改代码。
"""

from bridge import config

DEFAULT_TRIGGER_WORDS = "助手,机器人,gpt,claude,chatgpt"
DEFAULT_QUESTION_WORDS = "吗,呢,如何,怎么,为什么,什么,是否,能不能,可不可以,多少,多久,有没有,是不是,谁,哪位,叫什么"
DEFAULT_REQUEST_WORDS = "帮我,帮忙,请教,请,麻烦,解释,总结,分析,评价,推荐,整理,翻译,改写,润色,写个,写一个,生成,求"
DEFAULT_CONTROVERSIAL_TOPICS = (
    "炒股,股票,股市,a股,港股,美股,大盘,买股,卖股,持仓,仓位,抄底,追高,割肉,"
    "加仓,减仓,涨停,跌停,基金,定投,期货,黄金,比特币,虚拟币,加密货币,救市,"
    "买入,卖出,建仓,清仓,止盈,止损,抄底,追高,牛股,熊市,多头,空头,行情,大盘,"
    "政治,选举,领导人"
)

REFUSAL = "我不掌握相关信息，下一个问题"

DEFAULT_BLOCK_WORDS = (
    "傻逼,煞笔,傻比,垃圾东西,垃圾玩意,滚蛋,滚开,滚犊子,闭嘴,放屁,扯淡,胡扯,"
    "放你妈,你妈的,你他妈,什么玩意,啥玩意,无脑,脑残,智障,弱智,黑子,带节奏,"
    "杠精,抬杠,对线,开撕,撕逼,吵架,喷子,"
    "stupid,idiot,moron,retard,shut up,garbage"
)


def _words(key: str, default: str) -> set:
    raw = config.get(key, "") or default
    return {w.strip().lower() for w in raw.split(",") if w.strip()}


def is_question(text: str) -> bool:
    """是不是提问、点名、明确请求。

    不再拿它决定「回不回」——闲聊照样回；它只用来区分闲聊，
    闲聊的回复会计数（见 core 里的冻结逻辑）。
    """
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if "？" in raw or "?" in raw:
        return True
    if any(w in low for w in _words("TRIGGER_WORDS", DEFAULT_TRIGGER_WORDS)):
        return True
    if any(w in raw for w in _words("QUESTION_WORDS", DEFAULT_QUESTION_WORDS)):
        return True
    return any(w in raw for w in _words("REQUEST_WORDS", DEFAULT_REQUEST_WORDS))


def is_chitchat(text: str) -> bool:
    """闲聊：既不是提问也不是请求。照样回，但每次回复都计数。"""
    return not is_question(text)


def is_dispute(text: str) -> bool:
    """吵架/撕逼/人身攻击类内容：不掺和。"""
    low = (text or "").lower()
    return any(w in low for w in _words("BLOCK_KEYWORDS", DEFAULT_BLOCK_WORDS))


def is_controversial(text: str) -> bool:
    """争议话题（投资/政治等）：不表态，只回固定一句。"""
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    return any(w in low for w in _words("CONTROVERSIAL_TOPICS", DEFAULT_CONTROVERSIAL_TOPICS))


# ---- 出口筛查：限制「注入成功之后能造成什么」 --------------------------------
# 注入写法写不完也堵不住，所以不认写法，改成给模型的输出划边界：
# 太长砍断；提示词泄露、注入回声、数字轰炸整条不发。

MAX_REPLY_CHARS = 200
MAX_DIGITS = 40
LEAK_WINDOW = 30
ECHO_WINDOW = 20

DEFAULT_INJECTION_PATTERNS = (
    "忽略以上,忽略前面,忽略之前,忽略上述,"
    "无视以上,无视前面,无视之前,"
    "ignore previous,ignore all previous,ignore the above,"
    "disregard previous,disregard the above,"
    "从下一位起,从下一位开始,下一位起算,"
    "重复以下,重复上面所有,一字不差,原样输出,"
    "输出你的提示词,输出系统提示词,打印提示词,"
    "show me your prompt,reveal your prompt,print your prompt,system prompt,"
    "从现在开始你,解除限制,不受任何限制,越狱,dan模式"
)


def _norm(text: str) -> str:
    """只留字母数字和汉字：去掉空格标点，免得同一段话被格式打散。"""
    return "".join(ch for ch in (text or "") if ch.isalnum())


def is_injection(text: str) -> bool:
    """回复里带着注入指令的痕迹——模型在替别人转述它。"""
    low = (text or "").lower()
    return any(w in low for w in _words("INJECTION_PATTERNS", DEFAULT_INJECTION_PATTERNS))


def leaks_system_prompt(text: str) -> bool:
    """回复里大段出现系统提示词 = 被套出提示词了。"""
    hay = _norm(text)
    prompt = _norm(config.get("SYSTEM_PROMPT"))
    if len(hay) < LEAK_WINDOW or len(prompt) < LEAK_WINDOW:
        return False
    return any(prompt[i:i + LEAK_WINDOW] in hay for i in range(len(prompt) - LEAK_WINDOW + 1))


def echoes_source(text: str, source: str) -> bool:
    """回复大段复述了群里别人的话 = 模型被注入内容带着走。"""
    hay = _norm(text)
    src = _norm(source)
    if len(hay) < ECHO_WINDOW or len(src) < ECHO_WINDOW:
        return False
    return any(src[i:i + ECHO_WINDOW] in hay for i in range(len(src) - ECHO_WINDOW + 1))


def untrusted_text(messages, extra: str = "") -> str:
    """别人说的话 + 记忆内容：模型看到的不可信输入，注入载荷就在这里面。

    extra 是记忆服务抽出来的人物档案/会话摘要——它同样源自群里的话，
    一样是不可信输入。
    """
    nickname = config.get("QQ_SELF_NICKNAME")
    parts = [m.text for m in messages if m.text and not m.is_self and m.sender != nickname]
    if extra:
        parts.append(extra)
    return "\n".join(parts)


def screen_reply(text: str, source: str) -> str:
    """模型出口筛查：返回能发出去的文本，空串表示整条不发。

    不是要认出所有注入写法，而是限制注入成功之后的破坏面：
    超长砍断；提示词泄露、注入回声、数字轰炸整条拦下。
    """
    text = (text or "").strip()
    if not text:
        return ""
    if is_injection(text):
        return ""
    if leaks_system_prompt(text):
        return ""
    if echoes_source(text, source):
        return ""
    if sum(ch.isdigit() for ch in text) > MAX_DIGITS:
        return ""
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS] + "…"
    return text
