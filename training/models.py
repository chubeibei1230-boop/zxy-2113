from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_MANAGER = 'manager'
    ROLE_EXECUTOR = 'executor'
    ROLE_REVIEWER = 'reviewer'
    ROLE_CHOICES = [
        (ROLE_MANAGER, '管理者'),
        (ROLE_EXECUTOR, '执行者'),
        (ROLE_REVIEWER, '复核者'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_EXECUTOR)

    class Meta:
        db_table = 'auth_user'


class Instructor(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    bio = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'training_instructor'

    def __str__(self):
        return self.name


class Course(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, default='')
    duration_hours = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'training_course'

    def __str__(self):
        return f'{self.code} - {self.name}'


class Batch(models.Model):
    STATUS_PLANNED = 'planned'
    STATUS_ONGOING = 'ongoing'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PLANNED, '计划中'),
        (STATUS_ONGOING, '进行中'),
        (STATUS_COMPLETED, '已结束'),
        (STATUS_CANCELLED, '已取消'),
    ]
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='batches')
    name = models.CharField(max_length=200)
    instructor = models.ForeignKey(Instructor, on_delete=models.SET_NULL, null=True, blank=True, related_name='batches')
    start_date = models.DateField()
    end_date = models.DateField()
    capacity = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    location = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'training_batch'

    def __str__(self):
        return f'{self.course.code} - {self.name}'


class Student(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, db_index=True)
    email = models.EmailField(blank=True, default='')
    id_number = models.CharField(max_length=50, blank=True, default='')
    company = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'training_student'
        unique_together = ['name', 'phone']

    def __str__(self):
        return f'{self.name} ({self.phone})'


class Registration(models.Model):
    FEE_UNPAID = 'unpaid'
    FEE_PARTIAL = 'partial'
    FEE_PAID = 'paid'
    FEE_REFUNDED = 'refunded'
    FEE_CHOICES = [
        (FEE_UNPAID, '未缴费'),
        (FEE_PARTIAL, '部分缴费'),
        (FEE_PAID, '已缴费'),
        (FEE_REFUNDED, '已退费'),
    ]
    STATUS_REGISTERED = 'registered'
    STATUS_ENROLLED = 'enrolled'
    STATUS_CANCELLED = 'cancelled'
    STATUS_DROPPED = 'dropped'
    STATUS_CHOICES = [
        (STATUS_REGISTERED, '已报名'),
        (STATUS_ENROLLED, '已入学'),
        (STATUS_CANCELLED, '已取消'),
        (STATUS_DROPPED, '已退学'),
    ]
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='registrations')
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='registrations')
    fee_status = models.CharField(max_length=20, choices=FEE_CHOICES, default=FEE_UNPAID)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_REGISTERED)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'training_registration'
        unique_together = ['student', 'batch']

    def __str__(self):
        return f'{self.student.name} - {self.batch.name}'


class CheckIn(models.Model):
    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name='checkins')
    check_in_date = models.DateField()
    check_in_time = models.TimeField(null=True, blank=True)
    method = models.CharField(max_length=50, blank=True, default='manual')
    operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    remark = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'training_checkin'
        unique_together = ['registration', 'check_in_date']

    def __str__(self):
        return f'{self.registration.student.name} - {self.check_in_date}'


class CertificateTemplate(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='certificate_templates')
    name = models.CharField(max_length=200)
    template_content = models.TextField(blank=True, default='', help_text='证书模板内容，支持变量: {name}, {course}, {date}, {batch}')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'training_certificate_template'

    def __str__(self):
        return self.name


class Certificate(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_ISSUED = 'issued'
    STATUS_REVOKED = 'revoked'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待发证'),
        (STATUS_ISSUED, '已发证'),
        (STATUS_REVOKED, '已撤销'),
    ]
    registration = models.ForeignKey(Registration, on_delete=models.PROTECT, related_name='certificates')
    template = models.ForeignKey(CertificateTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    certificate_no = models.CharField(max_length=100, unique=True, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    issued_date = models.DateField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_certificates')
    remark = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'training_certificate'

    def __str__(self):
        return f'{self.certificate_no or "N/A"} - {self.registration.student.name}'


class ImportError(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='import_errors')
    row_number = models.PositiveIntegerField()
    raw_data = models.TextField(blank=True, default='')
    error_type = models.CharField(max_length=50)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'training_import_error'
        ordering = ['row_number']

    def __str__(self):
        return f'Row {self.row_number}: {self.error_type}'
