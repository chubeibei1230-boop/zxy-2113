import csv
import io
import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Count, Prefetch
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import (
    Instructor, Course, Batch, Student, Registration,
    CheckIn, CertificateTemplate, Certificate, ImportError,
)
from .serializers import (
    UserSerializer, UserCreateSerializer,
    InstructorSerializer, CourseSerializer,
    BatchSerializer, BatchCreateSerializer,
    StudentSerializer,
    RegistrationSerializer, RegistrationCreateSerializer,
    CheckInSerializer, CertificateTemplateSerializer,
    CertificateSerializer, ImportErrorSerializer,
    CSVImportResultSerializer, BulkCheckInSerializer,
    BulkCertificateReviewSerializer,
)
from .permissions import IsManager, IsExecutor, IsReviewer, IsManagerOrExecutor, IsManagerOrReviewer
from .filters import RegistrationFilter, BatchFilter, CertificateFilter, CheckInFilter

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = UserCreateSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        if data.get('role') == User.ROLE_MANAGER:
            data['role'] = User.ROLE_EXECUTOR
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
    queryset = Batch.objects.select_related('course', 'instructor').all()
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

        registration_ids = serializer.validated_data['registration_ids']
        check_in_date = serializer.validated_data['check_in_date']
        method = serializer.validated_data.get('method', 'manual')
        remark = serializer.validated_data.get('remark', '')

        created = []
        skipped = []
        for reg_id in registration_ids:
            try:
                reg = Registration.objects.get(pk=reg_id)
                obj, created_flag = CheckIn.objects.get_or_create(
                    registration=reg,
                    check_in_date=check_in_date,
                    defaults={
                        'method': method,
                        'operator': request.user,
                        'remark': remark,
                    }
                )
                if created_flag:
                    created.append(CheckInSerializer(obj).data)
                else:
                    skipped.append({'registration_id': reg_id, 'reason': '已签到'})
            except Registration.DoesNotExist:
                skipped.append({'registration_id': reg_id, 'reason': '报名记录不存在'})

        return Response({
            'created_count': len(created),
            'skipped_count': len(skipped),
            'created': created,
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

        certificate_ids = serializer.validated_data['certificate_ids']
        action_type = serializer.validated_data['action']
        remark = serializer.validated_data.get('remark', '')

        updated = []
        errors = []
        for cert_id in certificate_ids:
            try:
                cert = Certificate.objects.get(pk=cert_id)
                if action_type == 'issue':
                    if cert.status != Certificate.STATUS_PENDING:
                        errors.append({'certificate_id': cert_id, 'reason': f'当前状态为{cert.get_status_display()}，无法发证'})
                        continue
                    cert.status = Certificate.STATUS_ISSUED
                    cert.issued_date = date.today()
                    cert.reviewed_by = request.user
                    cert.remark = remark
                    if not cert.certificate_no:
                        cert.certificate_no = f'CERT-{uuid.uuid4().hex[:12].upper()}'
                    cert.save()
                    updated.append(CertificateSerializer(cert).data)
                elif action_type == 'revoke':
                    if cert.status != Certificate.STATUS_ISSUED:
                        errors.append({'certificate_id': cert_id, 'reason': f'当前状态为{cert.get_status_display()}，无法撤销'})
                        continue
                    cert.status = Certificate.STATUS_REVOKED
                    cert.reviewed_by = request.user
                    cert.remark = remark
                    cert.save()
                    updated.append(CertificateSerializer(cert).data)
            except Certificate.DoesNotExist:
                errors.append({'certificate_id': cert_id, 'reason': '证书记录不存在'})

        return Response({
            'updated_count': len(updated),
            'error_count': len(errors),
            'updated': updated,
            'errors': errors,
        })


class CSVImportView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsExecutor]
    serializer_class = None

    def post(self, request, batch_id):
        try:
            batch = Batch.objects.select_related('course').get(pk=batch_id)
        except Batch.DoesNotExist:
            return Response({'detail': '班次不存在'}, status=status.HTTP_404_NOT_FOUND)

        file = request.FILES.get('file')
        if not file:
            return Response({'detail': '请上传CSV文件'}, status=status.HTTP_400_BAD_REQUEST)

        if not file.name.endswith('.csv'):
            return Response({'detail': '文件格式必须为CSV'}, status=status.HTTP_400_BAD_REQUEST)

        raw_bytes = file.read()
        decoded = None
        for encoding in ['utf-8-sig', 'gbk', 'utf-8']:
            try:
                decoded = raw_bytes.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if decoded is None:
            return Response({'detail': '文件编码不支持，请使用UTF-8或GBK编码'}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(io.StringIO(decoded))
        rows = list(reader)

        if not rows:
            return Response({'detail': 'CSV文件为空'}, status=status.HTTP_400_BAD_REQUEST)

        total_rows = len(rows)
        success_count = 0
        all_errors = []
        valid_fee_statuses = [c[0] for c in Registration.FEE_CHOICES]
        phones_in_batch = set(
            Registration.objects.filter(batch=batch).values_list(
                'student__phone', flat=True
            )
        )
        phones_in_import = {}

        for idx, row in enumerate(rows, start=1):
            row_errors = []
            raw_line = ','.join(f'{k}={v}' for k, v in row.items())

            name = row.get('name', '').strip() or row.get('姓名', '').strip()
            phone = row.get('phone', '').strip() or row.get('手机号', '').strip()
            email = row.get('email', '').strip() or row.get('邮箱', '').strip()
            id_number = row.get('id_number', '').strip() or row.get('身份证号', '').strip()
            company = row.get('company', '').strip() or row.get('公司', '').strip()
            fee_status_raw = row.get('fee_status', '').strip() or row.get('费用状态', '').strip()
            fee_amount_raw = row.get('fee_amount', '0').strip() or row.get('费用金额', '0').strip()

            if not name:
                row_errors.append({
                    'error_type': 'name_missing',
                    'error_message': '姓名缺失',
                })

            if not phone:
                row_errors.append({
                    'error_type': 'phone_missing',
                    'error_message': '手机号缺失',
                })
            else:
                if phone in phones_in_batch:
                    row_errors.append({
                        'error_type': 'phone_duplicate',
                        'error_message': f'手机号 {phone} 在该班次中已存在',
                    })
                elif phone in phones_in_import:
                    row_errors.append({
                        'error_type': 'phone_duplicate',
                        'error_message': f'手机号 {phone} 在本次导入中重复（首次出现在第{phones_in_import[phone]}行）',
                    })
                else:
                    phones_in_import[phone] = idx

            course_code = row.get('course_code', '').strip() or row.get('课程代码', '').strip()
            if course_code and course_code != batch.course.code:
                row_errors.append({
                    'error_type': 'course_not_found',
                    'error_message': f'课程代码 {course_code} 与班次课程 {batch.course.code} 不匹配',
                })

            if fee_status_raw and fee_status_raw not in valid_fee_statuses:
                row_errors.append({
                    'error_type': 'fee_status_invalid',
                    'error_message': f'费用状态 {fee_status_raw} 异常，有效值为: {", ".join(valid_fee_statuses)}',
                })

            if row_errors:
                for err in row_errors:
                    all_errors.append({
                        'row_number': idx,
                        'raw_data': raw_line,
                        'error_type': err['error_type'],
                        'error_message': err['error_message'],
                    })
                continue

            try:
                fee_status = fee_status_raw if fee_status_raw else Registration.FEE_UNPAID
                fee_amount = float(fee_amount_raw) if fee_amount_raw else 0

                with transaction.atomic():
                    student, _ = Student.objects.get_or_create(
                        name=name,
                        phone=phone,
                        defaults={
                            'email': email,
                            'id_number': id_number,
                            'company': company,
                        }
                    )
                    registration, created = Registration.objects.get_or_create(
                        student=student,
                        batch=batch,
                        defaults={
                            'fee_status': fee_status,
                            'fee_amount': fee_amount,
                            'status': Registration.STATUS_REGISTERED,
                        }
                    )
                    if not created:
                        all_errors.append({
                            'row_number': idx,
                            'raw_data': raw_line,
                            'error_type': 'registration_exists',
                            'error_message': f'{name}({phone}) 已在该班次报名',
                        })
                        phones_in_batch.add(phone)
                        continue

                    phones_in_batch.add(phone)
                    success_count += 1

            except Exception as e:
                all_errors.append({
                    'row_number': idx,
                    'raw_data': raw_line,
                    'error_type': 'system_error',
                    'error_message': str(e),
                })

        ImportError.objects.bulk_create([
            ImportError(
                batch=batch,
                row_number=e['row_number'],
                raw_data=e['raw_data'],
                error_type=e['error_type'],
                error_message=e['error_message'],
            ) for e in all_errors
        ])

        return Response({
            'total_rows': total_rows,
            'success_count': success_count,
            'error_count': len(all_errors),
            'errors': all_errors,
        }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unchecked_list(request):
    registrations = Registration.objects.select_related(
        'student', 'batch', 'batch__course', 'batch__instructor'
    ).filter(
        status__in=[Registration.STATUS_REGISTERED, Registration.STATUS_ENROLLED]
    )

    course_id = request.query_params.get('course')
    batch_id = request.query_params.get('batch')
    instructor_id = request.query_params.get('instructor')
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')

    if course_id:
        registrations = registrations.filter(batch__course_id=course_id)
    if batch_id:
        registrations = registrations.filter(batch_id=batch_id)
    if instructor_id:
        registrations = registrations.filter(batch__instructor_id=instructor_id)
    if start_date:
        registrations = registrations.filter(batch__start_date__gte=start_date)
    if end_date:
        registrations = registrations.filter(batch__end_date__lte=end_date)

    result = []
    for reg in registrations:
        checkin_dates = set(
            reg.checkins.values_list('check_in_date', flat=True)
        )
        if reg.batch.start_date and reg.batch.end_date:
            from datetime import timedelta
            current = reg.batch.start_date
            batch_dates = set()
            while current <= reg.batch.end_date:
                if current.weekday() < 5:
                    batch_dates.add(current)
                current += timedelta(days=1)
            missed = sorted(batch_dates - checkin_dates)
        else:
            missed = []

        if missed:
            result.append({
                'registration_id': reg.id,
                'student_name': reg.student.name,
                'student_phone': reg.student.phone,
                'batch_name': reg.batch.name,
                'course_name': reg.batch.course.name,
                'instructor_name': reg.batch.instructor.name if reg.batch.instructor else '',
                'total_days': len(batch_dates) if reg.batch.start_date and reg.batch.end_date else 0,
                'checked_in_days': len(checkin_dates),
                'missed_dates': [str(d) for d in missed],
            })

    return Response({
        'count': len(result),
        'results': result,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pending_certificates(request):
    certificates = Certificate.objects.select_related(
        'registration', 'registration__student', 'registration__batch',
        'registration__batch__course', 'registration__batch__instructor',
        'template',
    ).filter(status=Certificate.STATUS_PENDING)

    course_id = request.query_params.get('course')
    batch_id = request.query_params.get('batch')
    instructor_id = request.query_params.get('instructor')
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')

    if course_id:
        certificates = certificates.filter(registration__batch__course_id=course_id)
    if batch_id:
        certificates = certificates.filter(registration__batch_id=batch_id)
    if instructor_id:
        certificates = certificates.filter(registration__batch__instructor_id=instructor_id)
    if start_date:
        certificates = certificates.filter(registration__batch__start_date__gte=start_date)
    if end_date:
        certificates = certificates.filter(registration__batch__end_date__lte=end_date)

    cert_results = list(CertificateSerializer(certificates, many=True).data)

    existing_cert_reg_ids = set(
        Certificate.objects.filter(
            registration__isnull=False
        ).values_list('registration_id', flat=True)
    )

    eligible_regs = Registration.objects.select_related(
        'student', 'batch', 'batch__course', 'batch__instructor'
    ).filter(
        status=Registration.STATUS_ENROLLED,
        fee_status=Registration.FEE_PAID,
        batch__status=Batch.STATUS_COMPLETED,
    ).exclude(id__in=existing_cert_reg_ids)

    if course_id:
        eligible_regs = eligible_regs.filter(batch__course_id=course_id)
    if batch_id:
        eligible_regs = eligible_regs.filter(batch_id=batch_id)
    if instructor_id:
        eligible_regs = eligible_regs.filter(batch__instructor_id=instructor_id)
    if start_date:
        eligible_regs = eligible_regs.filter(batch__start_date__gte=start_date)
    if end_date:
        eligible_regs = eligible_regs.filter(batch__end_date__lte=end_date)

    auto_results = []
    for reg in eligible_regs:
        auto_results.append({
            'id': None,
            'student_name': reg.student.name,
            'student_phone': reg.student.phone,
            'batch_name': reg.batch.name,
            'course_name': reg.batch.course.name,
            'template_name': '',
            'reviewer_name': '',
            'certificate_no': '',
            'status': 'pending',
            'issued_date': None,
            'remark': '',
            'created_at': None,
            'updated_at': None,
            'registration': reg.id,
            'template': None,
            'reviewed_by': None,
        })

    return Response({
        'count': len(cert_results) + len(auto_results),
        'results': cert_results + auto_results,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def import_error_summary(request):
    batch_id = request.query_params.get('batch')
    errors = ImportError.objects.select_related('batch')

    if batch_id:
        errors = errors.filter(batch_id=batch_id)

    errors = errors.order_by('batch', 'row_number')

    summary = {}
    for err in errors:
        key = err.batch_id
        if key not in summary:
            summary[key] = {
                'batch_id': key,
                'batch_name': err.batch.name,
                'total_errors': 0,
                'error_types': {},
                'details': [],
            }
        summary[key]['total_errors'] += 1
        summary[key]['error_types'][err.error_type] = summary[key]['error_types'].get(err.error_type, 0) + 1
        summary[key]['details'].append(ImportErrorSerializer(err).data)

    return Response({
        'batch_count': len(summary),
        'results': list(summary.values()),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    from django.db.models import Count, Q

    total_students = Student.objects.count()
    total_registrations = Registration.objects.count()
    total_batches = Batch.objects.count()
    total_courses = Course.objects.count()
    pending_certificates_count = Certificate.objects.filter(status=Certificate.STATUS_PENDING).count()
    issued_certificates_count = Certificate.objects.filter(status=Certificate.STATUS_ISSUED).count()
    ongoing_batches = Batch.objects.filter(status=Batch.STATUS_ONGOING).count()

    batch_status_stats = dict(
        Batch.objects.values_list('status').annotate(count=Count('id'))
    )
    registration_status_stats = dict(
        Registration.objects.values_list('status').annotate(count=Count('id'))
    )
    fee_status_stats = dict(
        Registration.objects.values_list('fee_status').annotate(count=Count('id'))
    )

    return Response({
        'total_students': total_students,
        'total_registrations': total_registrations,
        'total_batches': total_batches,
        'total_courses': total_courses,
        'pending_certificates': pending_certificates_count,
        'issued_certificates': issued_certificates_count,
        'ongoing_batches': ongoing_batches,
        'batch_status_stats': batch_status_stats,
        'registration_status_stats': registration_status_stats,
        'fee_status_stats': fee_status_stats,
    })
