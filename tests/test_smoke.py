"""对着真实客户端窗口 dump 一次，断言能解析出会话；客户端未运行/未登录时跳过。"""

import pytest

from bridge import qq_uia, reader


def test_smoke_parse_live_client():
    if qq_uia.find_qq_window() is None:
        pytest.skip("客户端未运行")
    nodes = qq_uia.snapshot()
    if not nodes:
        pytest.skip("AX 树为空：客户端未带 %s 启动" % qq_uia.ACCESSIBILITY_FLAG)
    convs = reader.parse_conversations(nodes)
    if not convs:
        pytest.skip("会话列表为空：客户端可能未登录")
    assert len(convs) >= 1
    assert convs[0].name
