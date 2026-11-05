"""模型层：把「历史 + 本条消息」变成一条回复。

模型通道在 bridge/llm.py（harness 网关 / DashScope 二选一），本文件只管
消息怎么拼、提示词怎么拼、出口怎么筛。
"""

import datetime

from bridge import config, guard, llm

MAX_COMPLETION_TOKENS = llm.MAX_COMPLETION_TOKENS
WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def line(sender: str, text: str) -> str:
    """消息行格式：带说话人。群聊里模型只看正文认不出是谁在问。"""
    return "%s: %s" % (sender, text)


class Agent:
    def build_messages(self, history, user_text):
        """历史 + 本条消息 → messages（自己的发言算 assistant）。"""
        nickname = config.get("QQ_SELF_NICKNAME")
        messages = []
        for message in history:
            if not message.text:
                continue
            mine = message.is_self or message.sender == nickname
            role = "assistant" if mine else "user"
            messages.append({"role": role, "content": line(message.sender, message.text)})
        messages.append({"role": "user", "content": user_text})
        return messages

    @staticmethod
    def system_prompt(memory_note: str = "") -> str:
        """提示词 + 今天的日期（不给日期模型会瞎猜「今天周几」）+ 记忆。

        memory_note 为空时不追加任何东西——档案没有就是没有，
        提示词必须和没做记忆时逐字相同。
        """
        now = datetime.datetime.now()
        prompt = "%s\n（今天是 %s %s）" % (
            config.get("SYSTEM_PROMPT"),
            now.strftime("%Y-%m-%d"),
            WEEKDAYS[now.weekday()],
        )
        if memory_note:
            prompt += "\n\n" + memory_note
        return prompt

    def reply(self, conversation, history, user_text, memory_note: str = "") -> str:
        """调模型拿回复；出口再筛一道（模型被注入也得过这道）。"""
        # 模型看到的不可信输入（别人说的话 + 记忆里抽出来的话）
        source = guard.untrusted_text(history, memory_note) + "\n" + user_text
        text = llm.chat(
            self.system_prompt(memory_note),
            self.build_messages(history, user_text),
        )
        return guard.screen_reply(text, source)
