from .public import router as public_router
from .admin import router as admin_router
from .auth import router as auth_router
from .trading import router as trading_router
from .websocket import router as websocket_router
from .performance import router as performance_router

__all__ = ["public_router", "admin_router", "auth_router", "trading_router", "websocket_router", "performance_router"]
