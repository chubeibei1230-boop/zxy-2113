from rest_framework.permissions import BasePermission

from .constants import (
    ROLE_MANAGER, ROLE_EXECUTOR, ROLE_REVIEWER,
    ROLES_MANAGER_OR_EXECUTOR, ROLES_MANAGER_OR_REVIEWER,
)


class IsManager(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role == ROLE_MANAGER


class IsExecutor(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role == ROLE_EXECUTOR


class IsReviewer(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role == ROLE_REVIEWER


class IsManagerOrExecutor(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role in ROLES_MANAGER_OR_EXECUTOR


class IsManagerOrReviewer(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role in ROLES_MANAGER_OR_REVIEWER
