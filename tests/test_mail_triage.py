"""feat-006: two-stage triage. Offline — FakeChat + stub Gmail service."""

import pytest

from memoria.llm import FakeChat
from memoria.mail import (
    Email,
    archive,
    classify,
    fetch_messages,
    is_protected,
    request_archive,
)


class StubMessages:
    def __init__(self, store: dict):
        self.store = store
        self.archived: list[str] = []
        self._op = None

    # chaining: users().messages().list/get/modify(...).execute()
    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kw):
        self._op = ("list", kw)
        return self

    def get(self, **kw):
        self._op = ("get", kw)
        return self

    def modify(self, **kw):
        self._op = ("modify", kw)
        return self

    def execute(self):
        kind, kw = self._op
        if kind == "list":
            return {"messages": [{"id": mid} for mid in self.store]}
        if kind == "get":
            return self.store[kw["id"]]
        self.archived.append(kw["id"])  # modify
        return {}


def _full(mid, subject, sender, snippet):
    return {
        "id": mid,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
            ]
        },
    }


def test_verification_mail_protected_never_archivable():
    mail = Email("m1", "您的验证码", "no-reply@svc.com", "验证码 482917，5 分钟内有效")
    t = classify(mail, FakeChat("类别：通知\n摘要：登录验证码。"))
    assert t.protected and t.category == "通知"
    assert not t.archive_candidate
    assert request_archive(t) is None  # red line: no path to archive


def test_transaction_mail_protected():
    mail = Email("m2", "支付成功通知", "pay@x.com", "您有一笔订单支付成功，金额 99 元")
    t = classify(mail, FakeChat("类别：通知\n摘要：订单支付成功。"))
    assert t.protected
    assert request_archive(t) is None


def test_mixed_marketing_transaction_stays_protected():
    mail = Email("m3", "大促！顺便看下您的账单", "promo@x.com", "全场五折，账单已出请查收")
    t = classify(mail, FakeChat("类别：营销\n摘要：大促广告。"))
    assert t.category == "营销" and t.protected  # protection wins
    assert request_archive(t) is None


def test_pure_marketing_is_archivable_with_confirm():
    svc = StubMessages({"m4": _full("m4", "限时优惠", "promo@x.com", "全场三折")})
    mail = Email("m4", "限时优惠", "promo@x.com", "全场三折")
    t = classify(mail, FakeChat("类别：营销\n摘要：促销广告。"))
    assert t.archive_candidate
    assert request_archive(t) == "m4"
    with pytest.raises(PermissionError):  # no confirm -> no archive, ever
        archive(svc, "m4", confirmed=False)
    assert svc.archived == []
    archive(svc, "m4", confirmed=True)  # human clicked confirm
    assert svc.archived == ["m4"]


def test_classify_falls_back_on_garbage():
    mail = Email("m5", "Hi", "a@b.com", "mina snippet 内容")
    t = classify(mail, FakeChat("胡言乱语，没有格式"))
    assert t.category == "通知" and t.summary == "mina snippet 内容"


def test_fetch_messages_via_stub():
    svc = StubMessages({"m1": _full("m1", "主题一", "a@b.com", "摘要一")})
    mails = fetch_messages(svc, query="newer_than:1d", max_n=10)
    assert [(m.msg_id, m.subject, m.sender, m.snippet) for m in mails] == [
        ("m1", "主题一", "a@b.com", "摘要一")
    ]
