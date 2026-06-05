from datetime import timedelta

from django.db.models import Count

from ..models import (
    Student, Registration, Batch, Course, Certificate,
    CheckIn, ImportError,
)
from ..serializers import CertificateSerializer, ImportErrorSerializer


def get_unchecked_list(filters):
    registrations = Registration.objects.select_related(
        'student', 'batch', 'batch__course', 'batch__instructor'
    ).filter(
        status__in=[Registration.STATUS_REGISTERED, Registration.STATUS_ENROLLED]
    )

    course_id = filters.get('course')
    batch_id = filters.get('batch')
    instructor_id = filters.get('instructor')
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')

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
        checkin_dates = set(reg.checkins.values_list('check_in_date', flat=True))
        if reg.batch.start_date and reg.batch.end_date:
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

    return {'count': len(result), 'results': result}


def get_pending_certificates(filters):
    certificates = Certificate.objects.select_related(
        'registration', 'registration__student', 'registration__batch',
        'registration__batch__course', 'registration__batch__instructor',
        'template',
    ).filter(status=Certificate.STATUS_PENDING)

    course_id = filters.get('course')
    batch_id = filters.get('batch')
    instructor_id = filters.get('instructor')
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')

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
        Certificate.objects.filter(registration__isnull=False).values_list('registration_id', flat=True)
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

    return {
        'count': len(cert_results) + len(auto_results),
        'results': cert_results + auto_results,
    }


def get_import_error_summary(batch_id=None):
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

    return {
        'batch_count': len(summary),
        'results': list(summary.values()),
    }


def get_dashboard_stats():
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

    return {
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
    }
