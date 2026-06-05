import django_filters
from .models import Registration, Certificate, CheckIn, Batch, Graduation


class RegistrationFilter(django_filters.FilterSet):
    course = django_filters.NumberFilter(field_name='batch__course')
    batch = django_filters.NumberFilter(field_name='batch')
    status = django_filters.CharFilter(field_name='status')
    fee_status = django_filters.CharFilter(field_name='fee_status')
    instructor = django_filters.NumberFilter(field_name='batch__instructor')
    start_date = django_filters.DateFilter(field_name='batch__start_date', lookup_expr='gte')
    end_date = django_filters.DateFilter(field_name='batch__end_date', lookup_expr='lte')
    student_name = django_filters.CharFilter(field_name='student__name', lookup_expr='icontains')
    student_phone = django_filters.CharFilter(field_name='student__phone', lookup_expr='icontains')

    class Meta:
        model = Registration
        fields = ['course', 'batch', 'status', 'fee_status', 'instructor', 'start_date', 'end_date']


class BatchFilter(django_filters.FilterSet):
    course = django_filters.NumberFilter(field_name='course')
    instructor = django_filters.NumberFilter(field_name='instructor')
    status = django_filters.CharFilter(field_name='status')
    start_date = django_filters.DateFilter(field_name='start_date', lookup_expr='gte')
    end_date = django_filters.DateFilter(field_name='end_date', lookup_expr='lte')

    class Meta:
        model = Batch
        fields = ['course', 'instructor', 'status', 'start_date', 'end_date']


class CertificateFilter(django_filters.FilterSet):
    course = django_filters.NumberFilter(field_name='registration__batch__course')
    batch = django_filters.NumberFilter(field_name='registration__batch')
    status = django_filters.CharFilter(field_name='status')
    instructor = django_filters.NumberFilter(field_name='registration__batch__instructor')
    start_date = django_filters.DateFilter(field_name='registration__batch__start_date', lookup_expr='gte')
    end_date = django_filters.DateFilter(field_name='registration__batch__end_date', lookup_expr='lte')

    class Meta:
        model = Certificate
        fields = ['course', 'batch', 'status', 'instructor']


class CheckInFilter(django_filters.FilterSet):
    course = django_filters.NumberFilter(field_name='registration__batch__course')
    batch = django_filters.NumberFilter(field_name='registration__batch')
    instructor = django_filters.NumberFilter(field_name='registration__batch__instructor')
    check_in_date_start = django_filters.DateFilter(field_name='check_in_date', lookup_expr='gte')
    check_in_date_end = django_filters.DateFilter(field_name='check_in_date', lookup_expr='lte')

    class Meta:
        model = CheckIn
        fields = ['course', 'batch', 'instructor']


class GraduationFilter(django_filters.FilterSet):
    course = django_filters.NumberFilter(field_name='registration__batch__course')
    batch = django_filters.NumberFilter(field_name='registration__batch')
    status = django_filters.CharFilter(field_name='status')
    instructor = django_filters.NumberFilter(field_name='registration__batch__instructor')
    student_name = django_filters.CharFilter(field_name='registration__student__name', lookup_expr='icontains')
    student_phone = django_filters.CharFilter(field_name='registration__student__phone', lookup_expr='icontains')
    start_date = django_filters.DateFilter(field_name='registration__batch__start_date', lookup_expr='gte')
    end_date = django_filters.DateFilter(field_name='registration__batch__end_date', lookup_expr='lte')

    class Meta:
        model = Graduation
        fields = ['course', 'batch', 'status', 'instructor', 'student_name', 'student_phone']
