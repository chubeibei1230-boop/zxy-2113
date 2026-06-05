from ..models import Registration, CheckIn


def bulk_checkin(registration_ids, check_in_date, method, remark, operator):
    created = []
    skipped = []
    for reg_id in registration_ids:
        try:
            reg = Registration.objects.get(pk=reg_id)
            obj, created_flag = CheckIn.objects.get_or_create(
                registration=reg,
                check_in_date=check_in_date,
                defaults={'method': method, 'operator': operator, 'remark': remark}
            )
            if created_flag:
                created.append(obj)
            else:
                skipped.append({'registration_id': reg_id, 'reason': '已签到'})
        except Registration.DoesNotExist:
            skipped.append({'registration_id': reg_id, 'reason': '报名记录不存在'})
    return created, skipped
