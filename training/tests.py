import csv
import io
from datetime import date, timedelta

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from .models import (
    Instructor, Course, Batch, Student, Registration,
    CheckIn, CertificateTemplate, Certificate, ImportError,
)
from .constants import ROLE_MANAGER, ROLE_EXECUTOR, ROLE_REVIEWER
from .services.import_service import import_registrations, decode_csv_file, parse_csv_rows
from .services.checkin_service import bulk_checkin
from .services.certificate_service import bulk_review
from .services.report_service import (
    get_unchecked_list, get_pending_certificates,
    get_import_error_summary, get_dashboard_stats,
)

User = get_user_model()


def _make_csv(rows, header=None):
    if header is None:
        header = ['name', 'phone', 'email', 'id_number', 'company', 'fee_status', 'fee_amount', 'course_code']
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode('utf-8-sig')


class ConstantsTestCase(TestCase):
    def test_role_values(self):
        self.assertEqual(ROLE_MANAGER, 'manager')
        self.assertEqual(ROLE_EXECUTOR, 'executor')
        self.assertEqual(ROLE_REVIEWER, 'reviewer')

    def test_role_sets(self):
        from .constants import ROLES_MANAGER_OR_EXECUTOR, ROLES_MANAGER_OR_REVIEWER
        self.assertEqual(ROLES_MANAGER_OR_EXECUTOR, {'manager', 'executor'})
        self.assertEqual(ROLES_MANAGER_OR_REVIEWER, {'manager', 'reviewer'})


class PermissionTestCase(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='mgr', password='pass', role=ROLE_MANAGER)
        self.executor = User.objects.create_user(username='exe', password='pass', role=ROLE_EXECUTOR)
        self.reviewer = User.objects.create_user(username='rev', password='pass', role=ROLE_REVIEWER)

    def test_manager_permissions(self):
        from .permissions import IsManager, IsManagerOrExecutor, IsManagerOrReviewer

        class FakeRequest:
            def __init__(self, user):
                self.user = user

        self.assertTrue(IsManager().has_permission(FakeRequest(self.manager), None))
        self.assertFalse(IsManager().has_permission(FakeRequest(self.executor), None))

        self.assertTrue(IsManagerOrExecutor().has_permission(FakeRequest(self.manager), None))
        self.assertTrue(IsManagerOrExecutor().has_permission(FakeRequest(self.executor), None))
        self.assertFalse(IsManagerOrExecutor().has_permission(FakeRequest(self.reviewer), None))

        self.assertTrue(IsManagerOrReviewer().has_permission(FakeRequest(self.manager), None))
        self.assertTrue(IsManagerOrReviewer().has_permission(FakeRequest(self.reviewer), None))
        self.assertFalse(IsManagerOrReviewer().has_permission(FakeRequest(self.executor), None))


class ImportServiceTestCase(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='Test Course', code='TC01')
        self.instructor = Instructor.objects.create(name='Inst')
        self.batch = Batch.objects.create(
            course=self.course, instructor=self.instructor,
            name='Batch 1', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
            status=Batch.STATUS_ONGOING,
        )

    def test_decode_csv_utf8(self):
        raw = 'name,phone\n张三,13800001111'.encode('utf-8-sig')
        result = decode_csv_file(raw)
        self.assertIn('张三', result)

    def test_decode_csv_gbk(self):
        raw = 'name,phone\n张三,13800001111'.encode('gbk')
        result = decode_csv_file(raw)
        self.assertIn('张三', result)

    def test_decode_csv_unsupported(self):
        raw = b'\xff\xfe'
        result = decode_csv_file(raw)
        self.assertIsNone(result)

    def test_parse_csv_rows(self):
        decoded = 'name,phone\nAlice,111\nBob,222'
        rows = parse_csv_rows(decoded)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['name'], 'Alice')

    def test_import_registrations_success(self):
        csv_bytes = _make_csv([
            {'name': 'Alice', 'phone': '13800001111', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': ''},
        ])
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(error)
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['error_count'], 0)

    def test_import_registrations_batch_not_found(self):
        result, error = import_registrations(9999, b'')
        self.assertIsNone(result)
        self.assertEqual(error['detail'], '班次不存在')

    def test_import_registrations_empty_csv(self):
        csv_bytes = 'name,phone\n'.encode('utf-8-sig')
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(result)
        self.assertEqual(error['detail'], 'CSV文件为空')

    def test_import_registrations_missing_name(self):
        csv_bytes = _make_csv([
            {'name': '', 'phone': '13800001111', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': ''},
        ])
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(error)
        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['error_count'], 1)
        self.assertEqual(result['errors'][0]['error_type'], 'name_missing')

    def test_import_registrations_missing_phone(self):
        csv_bytes = _make_csv([
            {'name': 'Alice', 'phone': '', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': ''},
        ])
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(error)
        self.assertEqual(result['errors'][0]['error_type'], 'phone_missing')

    def test_import_registrations_duplicate_phone_in_batch(self):
        student = Student.objects.create(name='Bob', phone='13800002222')
        Registration.objects.create(student=student, batch=self.batch, status=Registration.STATUS_REGISTERED)

        csv_bytes = _make_csv([
            {'name': 'Bob2', 'phone': '13800002222', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': ''},
        ])
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(error)
        self.assertEqual(result['errors'][0]['error_type'], 'phone_duplicate')

    def test_import_registrations_duplicate_phone_in_import(self):
        csv_bytes = _make_csv([
            {'name': 'A', 'phone': '13800003333', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': ''},
            {'name': 'B', 'phone': '13800003333', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': ''},
        ])
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(error)
        dup_errors = [e for e in result['errors'] if e['error_type'] == 'phone_duplicate']
        self.assertEqual(len(dup_errors), 1)

    def test_import_registrations_course_code_mismatch(self):
        csv_bytes = _make_csv([
            {'name': 'Alice', 'phone': '13800004444', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': 'WRONG'},
        ])
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(error)
        self.assertEqual(result['errors'][0]['error_type'], 'course_not_found')

    def test_import_registrations_invalid_fee_status(self):
        csv_bytes = _make_csv([
            {'name': 'Alice', 'phone': '13800005555', 'email': '', 'id_number': '', 'company': '', 'fee_status': 'invalid', 'fee_amount': '0', 'course_code': ''},
        ])
        result, error = import_registrations(self.batch.id, csv_bytes)
        self.assertIsNone(error)
        self.assertEqual(result['errors'][0]['error_type'], 'fee_status_invalid')

    def test_import_registrations_unsupported_encoding(self):
        result, error = import_registrations(self.batch.id, b'\xff\xfe')
        self.assertIsNone(result)
        self.assertIn('编码', error['detail'])

    def test_import_registrations_creates_import_errors(self):
        csv_bytes = _make_csv([
            {'name': '', 'phone': '13800006666', 'email': '', 'id_number': '', 'company': '', 'fee_status': '', 'fee_amount': '0', 'course_code': ''},
        ])
        import_registrations(self.batch.id, csv_bytes)
        self.assertEqual(ImportError.objects.filter(batch=self.batch).count(), 1)


class CheckinServiceTestCase(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='C', code='C1')
        self.instructor = Instructor.objects.create(name='I')
        self.batch = Batch.objects.create(
            course=self.course, instructor=self.instructor,
            name='B', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
        )
        self.student = Student.objects.create(name='S', phone='13900001111')
        self.reg = Registration.objects.create(
            student=self.student, batch=self.batch, status=Registration.STATUS_REGISTERED,
        )
        self.operator = User.objects.create_user(username='op', password='pass', role=ROLE_EXECUTOR)

    def test_bulk_checkin_create(self):
        created, skipped = bulk_checkin(
            registration_ids=[self.reg.id],
            check_in_date=date(2025, 1, 10),
            method='manual', remark='', operator=self.operator,
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(created[0].check_in_date, date(2025, 1, 10))

    def test_bulk_checkin_skip_duplicate(self):
        CheckIn.objects.create(registration=self.reg, check_in_date=date(2025, 1, 10), operator=self.operator)
        created, skipped = bulk_checkin(
            registration_ids=[self.reg.id],
            check_in_date=date(2025, 1, 10),
            method='manual', remark='', operator=self.operator,
        )
        self.assertEqual(len(created), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn('已签到', skipped[0]['reason'])

    def test_bulk_checkin_missing_registration(self):
        created, skipped = bulk_checkin(
            registration_ids=[9999],
            check_in_date=date(2025, 1, 10),
            method='manual', remark='', operator=self.operator,
        )
        self.assertEqual(len(created), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn('不存在', skipped[0]['reason'])


class CertificateServiceTestCase(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='C', code='C1')
        self.instructor = Instructor.objects.create(name='I')
        self.batch = Batch.objects.create(
            course=self.course, instructor=self.instructor,
            name='B', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
        )
        self.student = Student.objects.create(name='S', phone='13900002222')
        self.reg = Registration.objects.create(
            student=self.student, batch=self.batch, status=Registration.STATUS_REGISTERED,
        )
        self.template = CertificateTemplate.objects.create(course=self.course, name='Tpl')
        self.reviewer = User.objects.create_user(username='rev', password='pass', role=ROLE_REVIEWER)
        self.cert = Certificate.objects.create(
            registration=self.reg, template=self.template, status=Certificate.STATUS_PENDING,
        )

    def test_bulk_review_issue(self):
        updated, errors = bulk_review(
            certificate_ids=[self.cert.id],
            action_type='issue', remark='ok', reviewer=self.reviewer,
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(len(errors), 0)
        self.cert.refresh_from_db()
        self.assertEqual(self.cert.status, Certificate.STATUS_ISSUED)
        self.assertIsNotNone(self.cert.certificate_no)
        self.assertEqual(self.cert.issued_date, date.today())

    def test_bulk_review_issue_not_pending(self):
        self.cert.status = Certificate.STATUS_ISSUED
        self.cert.save()
        updated, errors = bulk_review(
            certificate_ids=[self.cert.id],
            action_type='issue', remark='', reviewer=self.reviewer,
        )
        self.assertEqual(len(updated), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn('无法发证', errors[0]['reason'])

    def test_bulk_review_revoke(self):
        self.cert.status = Certificate.STATUS_ISSUED
        self.cert.save()
        updated, errors = bulk_review(
            certificate_ids=[self.cert.id],
            action_type='revoke', remark='bad', reviewer=self.reviewer,
        )
        self.assertEqual(len(updated), 1)
        self.cert.refresh_from_db()
        self.assertEqual(self.cert.status, Certificate.STATUS_REVOKED)

    def test_bulk_review_revoke_not_issued(self):
        updated, errors = bulk_review(
            certificate_ids=[self.cert.id],
            action_type='revoke', remark='', reviewer=self.reviewer,
        )
        self.assertEqual(len(updated), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn('无法撤销', errors[0]['reason'])

    def test_bulk_review_missing_certificate(self):
        updated, errors = bulk_review(
            certificate_ids=[9999],
            action_type='issue', remark='', reviewer=self.reviewer,
        )
        self.assertEqual(len(updated), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn('不存在', errors[0]['reason'])

    def test_bulk_review_generates_cert_no(self):
        self.cert.certificate_no = ''
        self.cert.save()
        updated, _ = bulk_review(
            certificate_ids=[self.cert.id],
            action_type='issue', remark='', reviewer=self.reviewer,
        )
        self.assertTrue(updated[0].certificate_no.startswith('CERT-'))


class ReportServiceTestCase(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name='C', code='C1')
        self.instructor = Instructor.objects.create(name='I')
        self.batch = Batch.objects.create(
            course=self.course, instructor=self.instructor,
            name='B', start_date=date(2025, 1, 6), end_date=date(2025, 1, 10),
            status=Batch.STATUS_ONGOING,
        )
        self.student = Student.objects.create(name='S', phone='13900003333')
        self.reg = Registration.objects.create(
            student=self.student, batch=self.batch, status=Registration.STATUS_ENROLLED,
        )

    def test_unchecked_list_with_missed_days(self):
        data = get_unchecked_list({})
        self.assertIn('results', data)
        found = any(r['registration_id'] == self.reg.id for r in data['results'])
        self.assertTrue(found)

    def test_unchecked_list_filter_by_batch(self):
        data = get_unchecked_list({'batch': self.batch.id})
        self.assertTrue(len(data['results']) >= 1)

    def test_unchecked_list_filter_by_course(self):
        data = get_unchecked_list({'course': self.course.id})
        self.assertTrue(len(data['results']) >= 1)

    def test_pending_certificates_includes_auto_eligible(self):
        self.batch.status = Batch.STATUS_COMPLETED
        self.batch.save()
        self.reg.fee_status = Registration.FEE_PAID
        self.reg.save()
        data = get_pending_certificates({})
        self.assertTrue(len(data['results']) >= 1)

    def test_import_error_summary_empty(self):
        data = get_import_error_summary()
        self.assertEqual(data['batch_count'], 0)

    def test_import_error_summary_with_errors(self):
        ImportError.objects.create(batch=self.batch, row_number=1, error_type='test', error_message='test')
        data = get_import_error_summary()
        self.assertEqual(data['batch_count'], 1)

    def test_import_error_summary_filter_by_batch(self):
        ImportError.objects.create(batch=self.batch, row_number=1, error_type='test', error_message='test')
        data = get_import_error_summary(batch_id=self.batch.id)
        self.assertEqual(data['batch_count'], 1)
        data2 = get_import_error_summary(batch_id=9999)
        self.assertEqual(data2['batch_count'], 0)

    def test_dashboard_stats(self):
        data = get_dashboard_stats()
        self.assertIn('total_students', data)
        self.assertIn('total_registrations', data)
        self.assertIn('total_batches', data)
        self.assertIn('total_courses', data)
        self.assertIn('batch_status_stats', data)
        self.assertIn('registration_status_stats', data)
        self.assertIn('fee_status_stats', data)


class APIEndpointTestCase(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='mgr', password='pass', role=ROLE_MANAGER)
        self.executor = User.objects.create_user(username='exe', password='pass', role=ROLE_EXECUTOR)
        self.client = APIClient()

    def test_register_endpoint(self):
        resp = self.client.post('/api/auth/register/', {
            'username': 'newuser', 'password': 'test123456', 'email': 'a@b.com', 'role': ROLE_EXECUTOR,
        })
        self.assertEqual(resp.status_code, 201)

    def test_register_prevents_manager_role(self):
        resp = self.client.post('/api/auth/register/', {
            'username': 'hack', 'password': 'test123456', 'email': 'a@b.com', 'role': ROLE_MANAGER,
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['user']['role'], ROLE_EXECUTOR)

    def test_dashboard_requires_auth(self):
        resp = self.client.get('/api/dashboard/')
        self.assertEqual(resp.status_code, 401)

    def test_dashboard_authenticated(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.get('/api/dashboard/')
        self.assertEqual(resp.status_code, 200)

    def test_bulk_checkin_endpoint(self):
        self.client.force_authenticate(user=self.executor)
        course = Course.objects.create(name='C', code='C1')
        batch = Batch.objects.create(
            course=course, name='B', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
        )
        student = Student.objects.create(name='S', phone='13900009999')
        reg = Registration.objects.create(student=student, batch=batch, status=Registration.STATUS_REGISTERED)

        resp = self.client.post('/api/checkins/bulk/', {
            'registration_ids': [reg.id], 'check_in_date': '2025-01-10',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['created_count'], 1)

    def test_bulk_review_endpoint(self):
        self.client.force_authenticate(user=self.manager)
        course = Course.objects.create(name='C', code='C2')
        batch = Batch.objects.create(
            course=course, name='B', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
        )
        student = Student.objects.create(name='S', phone='13900008888')
        reg = Registration.objects.create(student=student, batch=batch, status=Registration.STATUS_REGISTERED)
        template = CertificateTemplate.objects.create(course=course, name='Tpl')
        cert = Certificate.objects.create(registration=reg, template=template, status=Certificate.STATUS_PENDING)

        resp = self.client.post('/api/certificates/bulk-review/', {
            'certificate_ids': [cert.id], 'action': 'issue',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['updated_count'], 1)

    def test_csv_import_endpoint(self):
        self.client.force_authenticate(user=self.executor)
        course = Course.objects.create(name='C', code='C3')
        batch = Batch.objects.create(
            course=course, name='B', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
        )
        csv_content = 'name,phone\nTest,13900007777'
        csv_file = io.BytesIO(csv_content.encode('utf-8-sig'))
        csv_file.name = 'test.csv'

        resp = self.client.post(f'/api/import/{batch.id}/', {'file': csv_file})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['success_count'], 1)

    def test_csv_import_no_file(self):
        self.client.force_authenticate(user=self.executor)
        course = Course.objects.create(name='C', code='C4')
        batch = Batch.objects.create(
            course=course, name='B', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
        )
        resp = self.client.post(f'/api/import/{batch.id}/', {})
        self.assertEqual(resp.status_code, 400)

    def test_csv_import_non_csv_file(self):
        self.client.force_authenticate(user=self.executor)
        course = Course.objects.create(name='C', code='C5')
        batch = Batch.objects.create(
            course=course, name='B', start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
        )
        txt_file = io.BytesIO(b'not csv')
        txt_file.name = 'test.txt'
        resp = self.client.post(f'/api/import/{batch.id}/', {'file': txt_file})
        self.assertEqual(resp.status_code, 400)

    def test_unchecked_list_endpoint(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.get('/api/reports/unchecked/')
        self.assertEqual(resp.status_code, 200)

    def test_pending_certificates_endpoint(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.get('/api/reports/pending-certificates/')
        self.assertEqual(resp.status_code, 200)

    def test_import_error_summary_endpoint(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.get('/api/reports/import-errors/')
        self.assertEqual(resp.status_code, 200)
