"""业务异常与全局异常处理器。

约定：所有可预期的业务失败抛出 ``AppError`` 子类，由统一 handler 转成 JSON，
禁止在路由里直接 ``raise HTTPException`` 抛业务错误（除 401/403 由依赖层抛出）。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """业务异常基类。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "app_error"

    def __init__(self, message: str, *, detail: Any = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class AlreadyExistsError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "already_exists"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class AuthError(AppError):
    """未认证 / 令牌失效。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ValidationError(AppError):
    # 直接写 422 而非引用 Starlette 常量，避免不同版本命名（ENTITY/CONTENT）差异
    status_code = 422
    code = "validation_error"


class ConflictStateError(AppError):
    """资源状态冲突，例如向已锁定的周报写内容。"""

    status_code = status.HTTP_409_CONFLICT
    code = "state_conflict"


class WeakPasswordError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "weak_password"


class SSORequiredError(AppError):
    """账号已接入统一身份认证，不能用本地口令登录。

    前端据此**自动改走 SSO 登录接口**，用户只需输入一次账号密码。
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "sso_required"


class SSOUnavailable(AppError):
    """IdP 不可达或配置有误。

    必须与"用户名或密码错误"严格区分：否则 IdP 一挂，
    所有人只会看到"口令错误"，运维无从判断故障。
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "sso_unavailable"


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，统一响应体为 ``{code, message, detail?}``。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "validation_error",
                "message": "请求参数校验失败",
                "detail": exc.errors(),
            },
        )

    @app.exception_handler(IntegrityError)
    async def _handle_integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("数据库完整性冲突: %s", exc.orig)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "already_exists", "message": "数据冲突或已存在"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def _handle_sqlalchemy(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("未预期的数据库异常: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": "db_error", "message": "数据库操作失败，请联系管理员"},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": "internal_error", "message": "服务器内部错误"},
        )
