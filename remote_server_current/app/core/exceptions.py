from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, detail: str, status_code: int = 500) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class NotFoundError(AppError):
    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(detail, status_code=404)


class ConflictError(AppError):
    def __init__(self, detail: str = "Resource already exists") -> None:
        super().__init__(detail, status_code=409)


class AuthenticationError(AppError):
    def __init__(self, detail: str = "Authentication failed") -> None:
        super().__init__(detail, status_code=401)


class AuthorizationError(AppError):
    def __init__(self, detail: str = "Access denied") -> None:
        super().__init__(detail, status_code=403)


class ValidationError(AppError):
    def __init__(self, detail: str = "Validation failed") -> None:
        super().__init__(detail, status_code=422)


class SolverError(AppError):
    def __init__(self, detail: str = "Solver error") -> None:
        super().__init__(detail, status_code=422)


class DslCompileError(AppError):
    def __init__(self, detail: str = "DSL script compile error") -> None:
        super().__init__(detail, status_code=400)


# --- FastAPI exception handlers (register in app.main) ---

async def app_exception_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    from app.core.logger import logger

    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
