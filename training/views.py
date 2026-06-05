from django.contrib.auth import get_user_model
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .constants import ROLE_MANAGER, ROLE_EXECUTOR
from .models import (
    Instructor, Course, Batch, Student, Registration,
    CheckIn, CertificateTemplate, Certificate,
)
from .serializers import (
    UserSerializer, UserCreateSerializer,
    InstructorSerializer, CourseSerializer,
    BatchSerializer, BatchCreateSerializer,
    StudentSerializer,
    RegistrationSerializer, RegistrationCreateSerializer,
    CheckInSerializer, CertificateTemplateSerializer,
    CertificateSerializer,
    BulkCheckInSerializer, BulkCertificateReviewSerializer,
)
from .permissions import IsManager, IsExecutor, IsManagerOrExecutor, IsManagerOrReviewer
from .filters import RegistrationFilter, BatchFilter, CertificateFilter, CheckInFilter
from .services.import_service import import_registrations
from .services.checkin_service import bulk_checkin
from .services.certificate_service import bulk_review
from .services.report_service import (
    get_unchecked_list, get_pending_certificates,
    get_import_error_summary, get_dashboard_stats,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = UserCreateSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        if data.get('role') == ROLE_MANAGER:
            data['role'] = ROLE_EXECUTOR
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'user': UserSerializer(user).data,
            'message': '注册成功',
        }, status=status.HTTP_201_CREATED)


class InstructorViewSet(viewsets.ModelViewSet):
    queryset = Instructor.objects.all()
    serializer_class = InstructorSerializer
    permission_classes = [IsAuthenticated, IsManager]
    search_fields = ['name', 'phone']


class CourseViewSet(viewsets.ModelViewSet):
    queryset = Course.objects.all()
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated, IsManager]
    search_fields = ['name', 'code']
    filterset_fields = ['code']


class BatchViewSet(viewsets.ModelViewSet):
    queryset = Batch.objects.select_related('course', 'instructor').prefetch_related('registrations').all()
    permission_classes = [IsAuthenticated]
    filterset_class = BatchFilter

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BatchCreateSerializer
        return BatchSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsManager()]
        return [IsAuthenticated()]


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ['name', 'phone']
    filterset_fields = ['phone']


class RegistrationViewSet(viewsets.ModelViewSet):
    queryset = Registration.objects.select_related(
        'student', 'batch', 'batch__course', 'batch__instructor'
    ).prefetch_related('checkins').all()
    permission_classes = [IsAuthenticated]
    filterset_class = RegistrationFilter

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return RegistrationCreateSerializer
        return RegistrationSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsManagerOrExecutor()]
        return [IsAuthenticated()]


class CheckInViewSet(viewsets.ModelViewSet):
    queryset = CheckIn.objects.select_related(
        'registration', 'registration__student', 'operator'
    ).all()
    serializer_class = CheckInSerializer
    permission_classes = [IsAuthenticated, IsManagerOrExecutor]
    filterset_class = CheckInFilter

    def perform_create(self, serializer):
        serializer.save(operator=self.request.user)

    @action(detail=False, methods=['post'], url_path='bulk')
    def bulk_checkin(self, request):
        serializer = BulkCheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        created_objs, skipped = bulk_checkin(
            registration_ids=serializer.validated_data['registration_ids'],
            check_in_date=serializer.validated_data['check_in_date'],
            method=serializer.validated_data.get('method', 'manual'),
            remark=serializer.validated_data.get('remark', ''),
            operator=request.user,
        )

        return Response({
            'created_count': len(created_objs),
            'skipped_count': len(skipped),
            'created': [CheckInSerializer(obj).data for obj in created_objs],
            'skipped': skipped,
        })


class CertificateTemplateViewSet(viewsets.ModelViewSet):
    queryset = CertificateTemplate.objects.select_related('course').all()
    serializer_class = CertificateTemplateSerializer
    permission_classes = [IsAuthenticated, IsManager]
    filterset_fields = ['course', 'is_active']


class CertificateViewSet(viewsets.ModelViewSet):
    queryset = Certificate.objects.select_related(
        'registration', 'registration__student', 'registration__batch',
        'registration__batch__course', 'template', 'reviewed_by'
    ).all()
    serializer_class = CertificateSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = CertificateFilter

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'bulk_review']:
            return [IsAuthenticated(), IsManagerOrReviewer()]
        return [IsAuthenticated()]

    @action(detail=False, methods=['post'], url_path='bulk-review')
    def bulk_review(self, request):
        serializer = BulkCertificateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_objs, errors = bulk_review(
            certificate_ids=serializer.validated_data['certificate_ids'],
            action_type=serializer.validated_data['action'],
            remark=serializer.validated_data.get('remark', ''),
            reviewer=request.user,
        )

        return Response({
            'updated_count': len(updated_objs),
            'error_count': len(errors),
            'updated': [CertificateSerializer(cert).data for cert in updated_objs],
            'errors': errors,
        })


class CSVImportView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsExecutor]
    serializer_class = None

    def post(self, request, batch_id):
        file = request.FILES.get('file')
        if not file:
            return Response({'detail': '请上传CSV文件'}, status=status.HTTP_400_BAD_REQUEST)

        if not file.name.endswith('.csv'):
            return Response({'detail': '文件格式必须为CSV'}, status=status.HTTP_400_BAD_REQUEST)

        result, error = import_registrations(batch_id, file.read())

        if error:
            return Response(error, status=status.HTTP_404_NOT_FOUND if '不存在' in error.get('detail', '') else status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unchecked_list(request):
    data = get_unchecked_list(request.query_params)
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pending_certificates(request):
    data = get_pending_certificates(request.query_params)
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def import_error_summary(request):
    batch_id = request.query_params.get('batch')
    data = get_import_error_summary(batch_id=batch_id)
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    data = get_dashboard_stats()
    return Response(data)
