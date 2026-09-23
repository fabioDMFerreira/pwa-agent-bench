"""notify — tiny notification service: user lookup, template rendering, webhook delivery."""

from .config import Settings
from .service import NotificationService, Summary
from .templates import TemplateStore, render
from .users import User, UserDirectory
from .webhook import DeliveryResult, WebhookSender

__all__ = [
    "DeliveryResult",
    "NotificationService",
    "Settings",
    "Summary",
    "TemplateStore",
    "User",
    "UserDirectory",
    "WebhookSender",
    "render",
]
