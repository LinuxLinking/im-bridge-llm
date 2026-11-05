import threading
import time

from bridge import writer


def test_ui_lock_blocks_a_second_worker():
    """两个进程/线程不能同时操作同一个输入框，否则消息会互相搅乱。"""
    order = []
    first_inside = threading.Event()

    def first():
        with writer.ui_lock():
            order.append("in1")
            first_inside.set()
            time.sleep(0.4)
            order.append("out1")

    def second():
        first_inside.wait(2)
        with writer.ui_lock():
            order.append("in2")
            order.append("out2")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert order == ["in1", "out1", "in2", "out2"]


def test_ui_lock_is_reentrant_in_one_thread():
    """handle 内部还会调 send，同一线程重入不能自锁。"""
    with writer.ui_lock():
        with writer.ui_lock():
            pass
