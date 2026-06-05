from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Instructor, Course, Batch, Student, Registration,
    CheckIn, CertificateTemplate, Certificate, ImportError, Graduation,
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'is_active', 'date_joined']
        read_only_fields = ['date_joined']


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['id', 'username', 'password', 'email', 'role']

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class InstructorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instructor
        fields = '__all__'


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = '__all__'


class BatchSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    course_code = serializers.CharField(source='course.code', read_only=True)
    instructor_name = serializers.CharField(source='instructor.name', read_only=True, default='')
    registration_count = serializers.SerializerMethodField()

    class Meta:
        model = Batch
        fields = '__all__'

    def get_registration_count(self, obj):
        return obj.registrations.count()


class BatchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Batch
        fields = '__all__'


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = '__all__'


class RegistrationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)
    student_phone = serializers.CharField(source='student.phone', read_only=True)
    batch_name = serializers.CharField(source='batch.name', read_only=True)
    course_name = serializers.CharField(source='batch.course.name', read_only=True)
    checkin_count = serializers.SerializerMethodField()

    class Meta:
        model = Registration
        fields = '__all__'

    def get_checkin_count(self, obj):
        return obj.checkins.count()


class RegistrationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Registration
        fields = '__all__'


class CheckInSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='registration.student.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True, default='')

    class Meta:
        model = CheckIn
        fields = '__all__'


class CertificateTemplateSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)

    class Meta:
        model = CertificateTemplate
        fields = '__all__'


class CertificateSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='registration.student.name', read_only=True)
    student_phone = serializers.CharField(source='registration.student.phone', read_only=True)
    batch_name = serializers.CharField(source='registration.batch.name', read_only=True)
    course_name = serializers.CharField(source='registration.batch.course.name', read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True, default='')
    reviewer_name = serializers.CharField(source='reviewed_by.username', read_only=True, default='')

    class Meta:
        model = Certificate
        fields = '__all__'


class ImportErrorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportError
        fields = '__all__'


class CSVImportResultSerializer(serializers.Serializer):
    total_rows = serializers.IntegerField()
    success_count = serializers.IntegerField()
    error_count = serializers.IntegerField()
    errors = ImportErrorSerializer(many=True)


class BulkCheckInSerializer(serializers.Serializer):
    registration_ids = serializers.ListField(child=serializers.IntegerField())
    check_in_date = serializers.DateField()
    method = serializers.CharField(default='manual')
    remark = serializers.CharField(default='', allow_blank=True)


class BulkCertificateReviewSerializer(serializers.Serializer):
    certificate_ids = serializers.ListField(child=serializers.IntegerField())
    action = serializers.ChoiceField(choices=['issue', 'revoke'])
    remark = serializers.CharField(default='', allow_blank=True)


class GraduationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='registration.student.name', read_only=True)
    student_phone = serializers.CharField(source='registration.student.phone', read_only=True)
    batch_name = serializers.CharField(source='registration.batch.name', read_only=True)
    course_name = serializers.CharField(source='registration.batch.course.name', read_only=True)
    registration_status = serializers.CharField(source='registration.status', read_only=True)
    fee_status = serializers.CharField(source='registration.fee_status', read_only=True)
    checkin_count = serializers.SerializerMethodField()
    total_required_days = serializers.SerializerMethodField()
    graduated_by_name = serializers.CharField(source='graduated_by.username', read_only=True, default='')
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Graduation
        fields = '__all__'

    def get_checkin_count(self, obj):
        return obj.registration.checkins.count()

    def get_total_required_days(self, obj):
        from .services.graduation_service import _get_batch_required_dates
        dates = _get_batch_required_dates(obj.registration.batch)
        return len(dates)


class GraduationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Graduation
        fields = ['remark']


class EligibilityCheckSerializer(serializers.Serializer):
    batch = serializers.IntegerField(required=False)
    registration = serializers.IntegerField(required=False)


class BulkGraduationConfirmSerializer(serializers.Serializer):
    graduation_ids = serializers.ListField(child=serializers.IntegerField())
    remark = serializers.CharField(default='', allow_blank=True)
