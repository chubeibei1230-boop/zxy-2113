import csv
import io

from django.db import transaction

from ..constants import VALID_ENCODINGS
from ..models import Batch, Student, Registration, ImportError


def decode_csv_file(raw_bytes):
    for encoding in VALID_ENCODINGS:
        try:
            return raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def parse_csv_rows(decoded):
    reader = csv.DictReader(io.StringIO(decoded))
    return list(reader)


def _extract_row_fields(row):
    name = row.get('name', '').strip() or row.get('姓名', '').strip()
    phone = row.get('phone', '').strip() or row.get('手机号', '').strip()
    email = row.get('email', '').strip() or row.get('邮箱', '').strip()
    id_number = row.get('id_number', '').strip() or row.get('身份证号', '').strip()
    company = row.get('company', '').strip() or row.get('公司', '').strip()
    fee_status_raw = row.get('fee_status', '').strip() or row.get('费用状态', '').strip()
    fee_amount_raw = row.get('fee_amount', '0').strip() or row.get('费用金额', '0').strip()
    course_code = row.get('course_code', '').strip() or row.get('课程代码', '').strip()
    return {
        'name': name, 'phone': phone, 'email': email,
        'id_number': id_number, 'company': company,
        'fee_status_raw': fee_status_raw, 'fee_amount_raw': fee_amount_raw,
        'course_code': course_code,
    }


def _validate_row(fields, idx, batch, phones_in_batch, phones_in_import):
    row_errors = []
    valid_fee_statuses = [c[0] for c in Registration.FEE_CHOICES]

    if not fields['name']:
        row_errors.append({'error_type': 'name_missing', 'error_message': '姓名缺失'})

    if not fields['phone']:
        row_errors.append({'error_type': 'phone_missing', 'error_message': '手机号缺失'})
    else:
        if fields['phone'] in phones_in_batch:
            row_errors.append({
                'error_type': 'phone_duplicate',
                'error_message': f'手机号 {fields["phone"]} 在该班次中已存在',
            })
        elif fields['phone'] in phones_in_import:
            row_errors.append({
                'error_type': 'phone_duplicate',
                'error_message': f'手机号 {fields["phone"]} 在本次导入中重复（首次出现在第{phones_in_import[fields["phone"]]}行）',
            })

    if fields['course_code'] and fields['course_code'] != batch.course.code:
        row_errors.append({
            'error_type': 'course_not_found',
            'error_message': f'课程代码 {fields["course_code"]} 与班次课程 {batch.course.code} 不匹配',
        })

    if fields['fee_status_raw'] and fields['fee_status_raw'] not in valid_fee_statuses:
        row_errors.append({
            'error_type': 'fee_status_invalid',
            'error_message': f'费用状态 {fields["fee_status_raw"]} 异常，有效值为: {", ".join(valid_fee_statuses)}',
        })

    return row_errors


def import_registrations(batch_id, raw_bytes):
    try:
        batch = Batch.objects.select_related('course').get(pk=batch_id)
    except Batch.DoesNotExist:
        return None, {'detail': '班次不存在'}

    decoded = decode_csv_file(raw_bytes)
    if decoded is None:
        return None, {'detail': '文件编码不支持，请使用UTF-8或GBK编码'}

    rows = parse_csv_rows(decoded)
    if not rows:
        return None, {'detail': 'CSV文件为空'}

    total_rows = len(rows)
    success_count = 0
    all_errors = []
    phones_in_batch = set(
        Registration.objects.filter(batch=batch).values_list('student__phone', flat=True)
    )
    phones_in_import = {}

    for idx, row in enumerate(rows, start=1):
        raw_line = ','.join(f'{k}={v}' for k, v in row.items())
        fields = _extract_row_fields(row)
        row_errors = _validate_row(fields, idx, batch, phones_in_batch, phones_in_import)

        if row_errors:
            if fields['phone'] and fields['phone'] not in phones_in_batch and fields['phone'] not in phones_in_import:
                phones_in_import[fields['phone']] = idx
            for err in row_errors:
                all_errors.append({
                    'row_number': idx, 'raw_data': raw_line,
                    'error_type': err['error_type'], 'error_message': err['error_message'],
                })
            continue

        phones_in_import[fields['phone']] = idx

        try:
            fee_status = fields['fee_status_raw'] if fields['fee_status_raw'] else Registration.FEE_UNPAID
            fee_amount = float(fields['fee_amount_raw']) if fields['fee_amount_raw'] else 0

            with transaction.atomic():
                student, _ = Student.objects.get_or_create(
                    name=fields['name'], phone=fields['phone'],
                    defaults={'email': fields['email'], 'id_number': fields['id_number'], 'company': fields['company']}
                )
                registration, created = Registration.objects.get_or_create(
                    student=student, batch=batch,
                    defaults={'fee_status': fee_status, 'fee_amount': fee_amount, 'status': Registration.STATUS_REGISTERED}
                )
                if not created:
                    all_errors.append({
                        'row_number': idx, 'raw_data': raw_line,
                        'error_type': 'registration_exists',
                        'error_message': f'{fields["name"]}({fields["phone"]}) 已在该班次报名',
                    })
                    phones_in_batch.add(fields['phone'])
                    continue

                phones_in_batch.add(fields['phone'])
                success_count += 1

        except Exception as e:
            all_errors.append({
                'row_number': idx, 'raw_data': raw_line,
                'error_type': 'system_error', 'error_message': str(e),
            })

    ImportError.objects.bulk_create([
        ImportError(
            batch=batch, row_number=e['row_number'], raw_data=e['raw_data'],
            error_type=e['error_type'], error_message=e['error_message'],
        ) for e in all_errors
    ])

    return {
        'total_rows': total_rows,
        'success_count': success_count,
        'error_count': len(all_errors),
        'errors': all_errors,
    }, None
