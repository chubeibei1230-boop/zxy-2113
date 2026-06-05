from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from ..models import Graduation, Registration, Batch, CheckIn


def _get_batch_required_dates(batch):
    if not batch.start_date or not batch.end_date:
        return set()
    current = batch.start_date
    dates = set()
    while current <= batch.end_date:
        if current.weekday() < 5:
            dates.add(current)
        current += timedelta(days=1)
    return dates


def evaluate_eligibility(registration):
    if registration.status in [Registration.STATUS_CANCELLED, Registration.STATUS_DROPPED]:
        return Graduation.STATUS_INELIGIBLE

    if registration.batch.status != Batch.STATUS_COMPLETED:
        return Graduation.STATUS_INELIGIBLE

    fee_ok = registration.fee_status == Registration.FEE_PAID

    required_dates = _get_batch_required_dates(registration.batch)
    checkin_dates = set(registration.checkins.values_list('check_in_date', flat=True))
    checkin_ok = required_dates.issubset(checkin_dates) if required_dates else True

    if not fee_ok and not checkin_ok:
        return Graduation.STATUS_INELIGIBLE

    if not fee_ok:
        return Graduation.STATUS_PENDING_PAYMENT

    if not checkin_ok:
        return Graduation.STATUS_PENDING_CHECKIN

    return Graduation.STATUS_ELIGIBLE


def refresh_graduation_status(batch_id=None, registration_id=None):
    if registration_id:
        registrations = Registration.objects.filter(pk=registration_id)
    elif batch_id:
        registrations = Registration.objects.filter(
            batch_id=batch_id,
            status__in=[Registration.STATUS_REGISTERED, Registration.STATUS_ENROLLED],
        )
    else:
        registrations = Registration.objects.filter(
            status__in=[Registration.STATUS_REGISTERED, Registration.STATUS_ENROLLED],
        )

    results = []
    for reg in registrations.select_related('student', 'batch', 'batch__course'):
        eligibility = evaluate_eligibility(reg)

        graduation, created = Graduation.objects.get_or_create(
            registration=reg,
            defaults={'status': eligibility},
        )

        if not created and graduation.status != Graduation.STATUS_GRADUATED:
            graduation.status = eligibility
            graduation.save(update_fields=['status', 'updated_at'])

        required_dates = _get_batch_required_dates(reg.batch)
        checkin_dates = set(reg.checkins.values_list('check_in_date', flat=True))
        missed = sorted(required_dates - checkin_dates)

        results.append({
            'registration_id': reg.id,
            'student_name': reg.student.name,
            'student_phone': reg.student.phone,
            'batch_id': reg.batch_id,
            'batch_name': reg.batch.name,
            'course_name': reg.batch.course.name,
            'registration_status': reg.status,
            'fee_status': reg.fee_status,
            'total_required_days': len(required_dates),
            'checked_in_days': len(checkin_dates & required_dates),
            'missed_dates': [str(d) for d in missed],
            'graduation_id': graduation.id,
            'graduation_status': graduation.status,
            'graduation_status_display': graduation.get_status_display(),
            'graduated_at': graduation.graduated_at,
            'remark': graduation.remark,
        })

    return results


def batch_confirm_graduation(graduation_ids, remark, operator):
    confirmed = []
    errors = []
    now = timezone.now()

    for gid in graduation_ids:
        try:
            grad = Graduation.objects.get(pk=gid)
            if grad.status == Graduation.STATUS_GRADUATED:
                errors.append({'graduation_id': gid, 'reason': '该学员已结业'})
                continue
            if grad.status != Graduation.STATUS_ELIGIBLE:
                errors.append({
                    'graduation_id': gid,
                    'reason': f'当前状态为{grad.get_status_display()}，不可结业',
                })
                continue
            grad.status = Graduation.STATUS_GRADUATED
            grad.graduated_at = now
            grad.graduated_by = operator
            if remark:
                grad.remark = remark
            grad.save(update_fields=['status', 'graduated_at', 'graduated_by', 'remark', 'updated_at'])
            confirmed.append(grad)
        except Graduation.DoesNotExist:
            errors.append({'graduation_id': gid, 'reason': '结业记录不存在'})

    return confirmed, errors


def get_batch_graduation_stats(batch_id=None):
    graduations = Graduation.objects.select_related(
        'registration', 'registration__batch', 'registration__batch__course',
    )

    if batch_id:
        graduations = graduations.filter(registration__batch_id=batch_id)

    batch_stats = {}
    for grad in graduations:
        batch = grad.registration.batch
        key = batch.id
        if key not in batch_stats:
            batch_stats[key] = {
                'batch_id': batch.id,
                'batch_name': batch.name,
                'course_name': batch.course.name,
                'total': 0,
                'graduated_count': 0,
                'eligible_count': 0,
                'pending_checkin_count': 0,
                'pending_payment_count': 0,
                'ineligible_count': 0,
            }
        stats = batch_stats[key]
        stats['total'] += 1
        if grad.status == Graduation.STATUS_GRADUATED:
            stats['graduated_count'] += 1
        elif grad.status == Graduation.STATUS_ELIGIBLE:
            stats['eligible_count'] += 1
        elif grad.status == Graduation.STATUS_PENDING_CHECKIN:
            stats['pending_checkin_count'] += 1
        elif grad.status == Graduation.STATUS_PENDING_PAYMENT:
            stats['pending_payment_count'] += 1
        elif grad.status == Graduation.STATUS_INELIGIBLE:
            stats['ineligible_count'] += 1

    for stats in batch_stats.values():
        if stats['total'] > 0:
            stats['graduation_rate'] = round(stats['graduated_count'] / stats['total'] * 100, 1)
        else:
            stats['graduation_rate'] = 0.0

    return list(batch_stats.values())
