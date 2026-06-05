from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    RegisterView, InstructorViewSet, CourseViewSet, BatchViewSet,
    StudentViewSet, RegistrationViewSet, CheckInViewSet,
    CertificateTemplateViewSet, CertificateViewSet, CSVImportView,
    unchecked_list, pending_certificates, import_error_summary,
    dashboard_stats,
)

router = DefaultRouter()
router.register(r'instructors', InstructorViewSet)
router.register(r'courses', CourseViewSet)
router.register(r'batches', BatchViewSet)
router.register(r'students', StudentViewSet)
router.register(r'registrations', RegistrationViewSet)
router.register(r'checkins', CheckInViewSet)
router.register(r'certificate-templates', CertificateTemplateViewSet)
router.register(r'certificates', CertificateViewSet)

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('import/<int:batch_id>/', CSVImportView.as_view(), name='csv-import'),
    path('reports/unchecked/', unchecked_list, name='unchecked-list'),
    path('reports/pending-certificates/', pending_certificates, name='pending-certificates'),
    path('reports/import-errors/', import_error_summary, name='import-error-summary'),
    path('dashboard/', dashboard_stats, name='dashboard-stats'),
    path('', include(router.urls)),
]
