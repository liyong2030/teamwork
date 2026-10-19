"""安全相关测试：口令策略、Argon2id 哈希、JWT 令牌类型隔离。"""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_token,
    decode_token,
    generate_temp_password,
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.models.organization import User
from app.services import auth_service, permission
from app.services.auth_service import change_password, reset_password

from .conftest import make_department, make_user


@pytest.mark.parametrize(
    "password,expect_ok",
    [
        ("Short1!", False),          # 长度不足
        ("alllowercase123", False),  # 缺大写与符号
        ("ALLUPPERCASE123", False),  # 缺小写与符号
        ("Abcdefgh12", True),       # 大写+小写+数字已达三类（策略要求"至少三类"）
        ("Abcdefghijkl", False),    # 只有字母，不足三类
        ("Abcdefgh123!", True),     # 满足三类
        ("StrongPass1!", True),
        ("with space1A!", False),    # 含空格
    ],
)
def test_password_strength_policy(password: str, expect_ok: bool) -> None:
    ok, msg = validate_password_strength(password)
    assert ok is expect_ok, msg


def test_hash_and_verify() -> None:
    hashed = hash_password("StrongPass1!")
    assert hashed != "StrongPass1!"
    assert verify_password("StrongPass1!", hashed) is True
    assert verify_password("WrongPass1!", hashed) is False


def test_verify_corrupted_hash_returns_false() -> None:
    """哈希损坏不应抛异常，返回 False 即可（避免向调用方泄漏细节）。"""
    assert verify_password("anything", "not-a-valid-hash") is False


def test_needs_rehash_detects_legacy() -> None:
    legacy = "$argon2i$v=19$m=4096,t=1,p=1$c29tZXNhbHQ$abcdefghijklmnopqrstuvwxyz123456"
    assert needs_rehash(legacy) is True


def test_generated_password_always_valid() -> None:
    for _ in range(5):
        password = generate_temp_password()
        ok, _msg = validate_password_strength(password)
        assert ok is True


def test_tokens_are_typed_and_interchange_rejected() -> None:
    access = create_access_token(1)
    refresh = create_refresh_token(1)

    assert decode_token(access, expected_type="access") is not None
    assert decode_token(refresh, expected_type="refresh") is not None
    # 令牌类型必须隔离，防止用 refresh 直接调业务接口
    assert decode_token(refresh, expected_type="access") is None
    assert decode_token(access, expected_type="refresh") is None
    assert decode_token("garbage.token.value") is None


def test_expired_token_rejected() -> None:
    expired = create_token(
        "1",
        token_type="access",
        expires_delta=dt.timedelta(seconds=-10),
    )
    assert decode_token(expired, expected_type="access") is None


def test_change_password_flow(db) -> None:
    dept = make_department(db, "安全部")
    user = make_user(db, "sec", department=dept, password="StrongPass1!")

    with pytest.raises(Exception):  # 原密码错误
        change_password(db, user, "Wrong1!aaa", "AnotherPass2!")

    change_password(db, user, "StrongPass1!", "AnotherPass2!")
    assert user.must_change_password is False
    assert verify_password("AnotherPass2!", user.hashed_password) is True

    with pytest.raises(Exception):  # 新旧不能相同
        change_password(db, user, "AnotherPass2!", "AnotherPass2!")


def test_admin_reset_forces_change(db) -> None:
    dept = make_department(db, "安全部")
    user = make_user(db, "reset-me", department=dept)
    raw = reset_password(db, user)
    assert user.must_change_password is True
    assert verify_password(raw, user.hashed_password) is True
    ok, _ = validate_password_strength(raw)
    assert ok is True


def test_authenticate_rejects_inactive(db) -> None:
    dept = make_department(db, "安全部")
    user = make_user(db, "inactive", department=dept)
    user.is_active = False
    db.flush()

    from app.core.exceptions import AuthError

    with pytest.raises(AuthError):
        auth_service.authenticate(db, "inactive", "StrongPass1!")


def test_authenticate_unknown_user_uses_dummy_hash(db) -> None:
    """不存在的用户名也应走一次哈希运算，避免时序侧信道。

    这里只断言抛的是 AuthError（不区分"用户不存在"与"口令错误"）。
    """
    from app.core.exceptions import AuthError

    with pytest.raises(AuthError):
        auth_service.authenticate(db, "ghost-user", "StrongPass1!")


def test_permission_matrix(db) -> None:
    dept_a = make_department(db, "A部")
    dept_b = make_department(db, "B部")
    leader = make_user(db, "boss", department=dept_a, is_leader=True)
    member = make_user(db, "worker", department=dept_a)
    outsider = make_user(db, "other", department=dept_b)
    admin = make_user(db, "root", department=dept_b, is_superuser=True)

    # 组长可管辖本部门
    assert permission.can_manage_department(leader, dept_a.id) is True
    assert permission.can_manage_department(leader, dept_b.id) is False
    # 普通成员不能管辖任何部门
    assert permission.can_manage_department(member, dept_a.id) is False
    # 管理员全局
    assert permission.can_manage_department(admin, dept_a.id) is True

    # 代提交：组长可为本部门成员代提交，不能跨部门
    assert permission.can_proxy_submit(leader, member) is True
    assert permission.can_proxy_submit(leader, outsider) is False
    assert permission.can_proxy_submit(admin, outsider) is True
    # 不能给自己代提交
    assert permission.can_proxy_submit(leader, leader) is False

    # 可见范围
    assert dept_b.id not in permission.visible_department_ids(member, [dept_a.id, dept_b.id])
    assert set(permission.visible_department_ids(admin, [dept_a.id, dept_b.id])) == {
        dept_a.id,
        dept_b.id,
    }


def test_user_department_accessors(db) -> None:
    dept = make_department(db, "属性部")
    user = make_user(db, "props", department=dept, is_leader=True)
    assert user.department_ids == [dept.id]
    assert user.leader_department_ids == [dept.id]

    other: User = db.get(User, user.id)
    assert other.username == "props"
