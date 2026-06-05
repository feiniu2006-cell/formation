"""Cancellation helpers for long-running formation tool tasks."""

import threading
import time


CANCEL_EVENT = threading.Event()


class TaskCancelled(RuntimeError):
    """用户在 GUI 中请求取消当前任务。"""


def request_cancel():
    CANCEL_EVENT.set()


def clear_cancel_request():
    CANCEL_EVENT.clear()


def is_cancel_requested():
    return CANCEL_EVENT.is_set()


def check_cancelled():
    if is_cancel_requested():
        raise TaskCancelled("用户已取消当前任务")


def interruptible_sleep(seconds):
    """支持取消的等待。"""
    end_time = time.time() + seconds
    while time.time() < end_time:
        check_cancelled()
        time.sleep(min(0.2, end_time - time.time()))

