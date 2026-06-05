from rest_framework.permissions import BasePermission


class IsManager(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role == 'manager'


class IsExecutor(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role == 'executor'


class IsReviewer(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role == 'reviewer'


class IsManagerOrExecutor(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role in ['manager', 'executor']


class IsManagerOrReviewer(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.role in ['manager', 'reviewer']
