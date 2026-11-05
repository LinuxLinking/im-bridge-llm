from bridge import config, guard


def test_question_mark_is_a_question():
    assert guard.is_question("有人在吗？")
    assert guard.is_question("what is this?")


def test_question_word_is_a_question():
    assert guard.is_question("这个怎么实现")
    assert guard.is_question("有没有人知道")


def test_request_word_is_a_question():
    assert guard.is_question("帮我看下这个报错")
    assert guard.is_question("谁能总结一下")


def test_plain_chat_counts_as_chitchat():
    """闲聊照样回，只是要计数——所以它属于闲聊。"""
    assert guard.is_chitchat("今天天气不错")
    assert guard.is_chitchat("哈哈")
    assert guard.is_chitchat("早上好")
    assert not guard.is_question("今天天气不错")


def test_name_mention_is_a_question():
    assert guard.is_question("助手在吗")
    assert guard.is_question("助手帮忙看看")


def test_dispute_is_blocked():
    assert guard.is_dispute("你傻逼吧")
    assert guard.is_dispute("别扯淡了")
    assert guard.is_dispute("what a moron")
    assert not guard.is_dispute("今天天气不错")


def test_controversial_topics_are_detected():
    assert guard.is_controversial("分析下美国救市是抄底吗")
    assert guard.is_controversial("现在该买哪只股票")
    assert guard.is_controversial("聊聊这次选举")
    assert not guard.is_controversial("他是学生 分析下学生为什么烦人")
    assert not guard.is_controversial("晚上吃啥")


def test_normal_reply_passes_the_screen_unchanged():
    assert guard.screen_reply("今天天气不错", "") == "今天天气不错"


def test_too_long_reply_is_truncated():
    out = guard.screen_reply("啊" * 300, "")
    assert len(out) == guard.MAX_REPLY_CHARS + 1
    assert out.endswith("…")


def test_prompt_leak_is_dropped():
    """被套出提示词：整条不发，而不是发一半。"""
    leaked = "我的设定是：" + config.get("SYSTEM_PROMPT")
    assert guard.screen_reply(leaked, "") == ""


def test_injection_payload_echo_is_dropped():
    """群里塞的载荷被模型复述出来：整条不发。"""
    assert guard.screen_reply("好的，最后几位是 98000，从下一位起算是 988586", "") == ""


def test_digit_flood_is_dropped():
    """「算 π 的后 250 位」这种算不完的数字流：整条不发。"""
    digits = "".join(str(i % 10) for i in range(300))
    assert guard.screen_reply("3.14" + digits, "") == ""


def test_long_echo_of_group_message_is_dropped():
    """回复大段复述群里的话 = 模型在替别人转述内容。"""
    source = "把这句话翻译一下：the quick brown fox jumps over the lazy dog"
    reply = "翻译：the quick brown fox jumps over the lazy dog"
    assert guard.screen_reply(reply, source) == ""


def test_short_quote_is_not_treated_as_echo():
    source = "把这句话翻译一下：the quick brown fox jumps over the lazy dog"
    reply = "the fox 就是那只狐狸"
    assert guard.screen_reply(reply, source) == reply


def test_words_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("TRIGGER_WORDS", "机器人甲")
    assert guard.is_question("机器人甲在此")
    assert not guard.is_question("助手在此")
