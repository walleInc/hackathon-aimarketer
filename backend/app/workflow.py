"""Автомат статусов публикации. Публикация возможна ТОЛЬКО из статуса approved."""
from enum import Enum


class PostStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION = "revision"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


S = PostStatus

ALLOWED: dict[PostStatus, set[PostStatus]] = {
    S.DRAFT: {S.PENDING},
    S.PENDING: {S.APPROVED, S.REJECTED, S.REVISION, S.DRAFT},
    S.REVISION: {S.DRAFT},
    # существенная правка одобренного поста возвращает его на повторное согласование
    S.APPROVED: {S.PUBLISHING, S.PENDING},
    S.PUBLISHING: {S.PUBLISHED, S.FAILED},
    S.FAILED: {S.APPROVED, S.PENDING},
    S.REJECTED: set(),
    S.PUBLISHED: set(),
}


class InvalidTransition(Exception):
    pass


def check_transition(current: str, new: PostStatus) -> None:
    if new not in ALLOWED[PostStatus(current)]:
        raise InvalidTransition(f"{current} -> {new.value} запрещён")
