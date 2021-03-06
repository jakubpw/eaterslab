import abc
from calendar import monthrange
from datetime import datetime, timezone
from dateutil.parser import parse as timestamp_parse
from os.path import join as path_join
from pytz import utc

from django.core.files.storage import FileSystemStorage
from django.db.models import QuerySet, Avg
from django.utils.decorators import method_decorator
from django_filters import rest_framework as filters
from drf_yasg.openapi import Parameter, IN_HEADER, TYPE_STRING
from drf_yasg.utils import swagger_auto_schema

from rest_framework import views, viewsets, generics, mixins, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import FileUploadParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from server import settings

from .models import *
from .serializers import *


# Accept-Language header
accept_language_header = Parameter('Accept-Language', IN_HEADER, description='Language for response content',
                                   type=TYPE_STRING)
accept_language_decorator = swagger_auto_schema(manual_parameters=[accept_language_header])

# Camera auth headers
x_device_id_header = Parameter('X-DEVICE-ID', IN_HEADER, required=True, description='Camera device name', type=TYPE_STRING)
x_api_key_header = Parameter('X-API-KEY', IN_HEADER, required=True, description='Camera key', type=TYPE_STRING)
auth_headers_decorator = swagger_auto_schema(manual_parameters=[x_device_id_header, x_api_key_header])


class GetPostViewSet(viewsets.ModelViewSet):
    http_method_names = ['get', 'post']


class PostViewSet(viewsets.ModelViewSet):
    http_method_names = ['post']


class CafeteriaFilterSet(filters.FilterSet):
    open_from = filters.TimeFilter(method='get_open_from')
    open_to = filters.TimeFilter(method='get_open_to')
    open_now = filters.BooleanFilter(method='get_open_now')
    prefix_name = filters.CharFilter(method='get_name_prefix')
    owner_id = filters.NumberFilter(method='get_for_owner')
    have_vegs = filters.BooleanFilter(method='get_for_vegetarian')
    min_avg_review = filters.NumberFilter(method='get_with_min_review')

    class Meta:
        model = Cafeteria
        fields = ['open_from', 'open_to', 'open_now', 'prefix_name', 'owner_id', 'have_vegs', 'min_avg_review']

    def get_open_now(self, queryset, field_name, value):
        is_open = value
        now = datetime.now().time()
        if is_open is True:
            return queryset.filter(open_from__lte=now).filter(open_to__gte=now)
        elif is_open is False:
            return (queryset.filter(open_from__gt=now) | queryset.filter(open_to__lt=now)).distinct()
        else:
            return queryset

    def get_name_prefix(self, queryset, field_name, value):
        if value is None:
            return queryset
        prefix = value.strip()
        return queryset.filter(name__istartswith=prefix)

    def get_for_owner(self, queryset, field_name, value):
        owner_id = value
        if owner_id is None:
            return queryset
        return queryset.filter(owner_id=owner_id)

    def get_for_vegetarian(self, queryset, field_name, value):
        if value is None:
            return queryset
        for_vegs = FixedMenuOption.objects.filter(vegetarian=value).values_list('cafeteria_id')
        return queryset.filter(id__in=for_vegs)

    def get_open_from(self, queryset, field_name, value):
        if value is None:
            return queryset
        return queryset.filter(open_from__lte=value)

    def get_open_to(self, queryset, field_name, value):
        if value is None:
            return queryset
        return queryset.filter(open_to__gte=value)

    def get_with_min_review(self, queryset, field_name, value):
        if value is None:
            return queryset
        return queryset.annotate(avg_review=Avg('fixed_menu_options__avg_review_stars')).filter(avg_review__gte=value)


@method_decorator(name='list', decorator=accept_language_decorator)
@method_decorator(name='retrieve', decorator=accept_language_decorator)
class CafeteriaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Cafeteria.objects.all().order_by('id')
    serializer_class = CafeteriaSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = CafeteriaFilterSet


class CameraViewSet(viewsets.ModelViewSet):
    http_method_names = []
    queryset = Camera.objects.all().order_by('cafeteria')
    serializer_class = CameraSerializer


@method_decorator(name='create', decorator=auth_headers_decorator)
class CameraEventsViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    http_method_names = ['post']
    serializer_class = CameraEventSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            # queryset just for schema generation metadata
            return CameraEvent.objects.none()
        return CameraEvent.objects.filter(camera_id=self.kwargs['camera_pk'])

    def create(self, request, *args, **kwargs):
        is_many = isinstance(request.data, list)
        if not is_many:
            return super(CameraEventsViewSet, self).create(request, *args, **kwargs)
        else:
            serializer = self.get_serializer(data=request.data, many=True)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


@method_decorator(name='list', decorator=accept_language_decorator)
@method_decorator(name='retrieve', decorator=accept_language_decorator)
class FixedMenuOptionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FixedMenuOptionSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            # queryset just for schema generation metadata
            return FixedMenuOption.objects.none()
        return FixedMenuOption.objects.all().filter(cafeteria=self.kwargs['cafeteria_pk']).order_by('id')


class FixedMenuOptionReviewViewSet(PostViewSet):
    queryset = FixedMenuOptionReview.objects.all().order_by('id')
    serializer_class = FixedMenuOptionReviewSerializer


class CafeteriaFixedMenuOptionReviewViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FixedMenuOptionReviewSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            # queryset just for schema generation metadata
            return FixedMenuOptionReview.objects.none()
        return FixedMenuOptionReview.objects.all().filter(option_id=self.kwargs['option_pk']).order_by('id')


class StatsDivider:
    @abc.abstractmethod
    def get_timestamp_delta(self, time: datetime):
        pass


class HourStatsDivider(StatsDivider):
    def get_timestamp_delta(self, time: datetime):
        return timedelta(hours=1)


class DayStatsDivider(StatsDivider):
    def get_timestamp_delta(self, time: datetime):
        return timedelta(days=1)


class WeekStatsDivider(StatsDivider):
    def get_timestamp_delta(self, time: datetime):
        return timedelta(weeks=1)


class MonthStatsDivider(StatsDivider):
    def get_timestamp_delta(self, time: datetime):
        return timedelta(days=monthrange(time.year, time.month)[1])


class YearStatsDivider(StatsDivider):
    def get_timestamp_delta(self, time: datetime):
        return timedelta(days=(time.replace(year=time.year + 1) - time).days)


class TimeStampedFilterSet(filters.FilterSet):
    start_timestamp = filters.DateTimeFilter(required=False)
    end_timestamp = filters.DateTimeFilter(required=False)
    count = filters.NumberFilter(required=False)
    group_by = filters.CharFilter(required=False)


LONGEST_SUPPORTED_STATS_LEN = 1024
DEFAULT_GROUP_BY = HourStatsDivider


def timestamp_middle(begin: datetime, end:datetime):
    return begin + ((end - begin) / 2)


class StatsView(generics.ListAPIView):
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = TimeStampedFilterSet

    @abc.abstractmethod
    def get_full_queryset(self, cafeteria_id):
        pass

    @abc.abstractmethod
    def timestamp_field_name(self):
        pass

    @abc.abstractmethod
    def init_value(self, before_queryset: QuerySet):
        pass

    @abc.abstractmethod
    def next_count_value(self, count_value, curr_queryset: QuerySet, **kwargs):
        pass

    @abc.abstractmethod
    def map_to_result_objects(self, index, value, timestamp, cafeteria_pk):
        pass

    def filter_queryset(self, queryset):
        return queryset

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            # queryset just for schema generation metadata
            return []
        cafeteria_pk = self.kwargs.get('cafeteria_pk')
        req_count = self.request.query_params.get('count')
        start_string = self.request.query_params.get('start_timestamp')
        end_string = self.request.query_params.get('end_timestamp')
        group_by_string = self.request.query_params.get('group_by')
        divider = get_divider(group_by_string)()

        if start_string is None:
            timestamp_start = datetime.min + divider.get_timestamp_delta(datetime.min) + timedelta(days=1)
        else:
            timestamp_start = timestamp_parse(start_string)

        if end_string is None:
            timestamp_end = datetime.max - divider.get_timestamp_delta(datetime.max) - timedelta(days=1)
        else:
            timestamp_end = timestamp_parse(end_string)

        if cafeteria_pk is None:
            raise ValueError('required params not specified')
        count = LONGEST_SUPPORTED_STATS_LEN if req_count is None else min(int(req_count), LONGEST_SUPPORTED_STATS_LEN)

        lookup_lte = '%s__lte' % self.timestamp_field_name()
        lookup_gt = '%s__gt' % self.timestamp_field_name()

        data = self.get_full_queryset(cafeteria_pk)
        before_data = data.filter(**{lookup_lte: timestamp_start}).order_by(self.timestamp_field_name())
        value_holder = self.init_value(before_data)
        begin = timestamp_start
        end = timestamp_start + divider.get_timestamp_delta(timestamp_start)

        curr_queryset = data.filter(**{lookup_gt: begin, lookup_lte: end}) \
            .order_by(self.timestamp_field_name())
        value_holder = self.next_count_value(value_holder, curr_queryset, begin=begin, end=end)
        results = [(value_holder, timestamp_middle(begin, end))]
        for interval_i in range(int(count) - 1):
            finish_now = False
            if end.astimezone() > datetime.now().astimezone() \
                    or end.astimezone() > timestamp_end.astimezone():
                end = datetime.now().astimezone()
                finish_now = True

            curr_queryset = data.filter(**{lookup_gt: begin, lookup_lte: end}) \
                .order_by(self.timestamp_field_name())
            value_holder = self.next_count_value(value_holder, curr_queryset, begin=begin, end=end)
            begin += divider.get_timestamp_delta(begin)
            end += divider.get_timestamp_delta(begin)
            results.append((value_holder, timestamp_middle(begin, end)))

            if finish_now:
                break

        return [self.map_to_result_objects(index, value, timestamp, cafeteria_pk)
                for index, (value, timestamp) in enumerate(results)]


def get_divider(group_by):
    available = {
        'hour': HourStatsDivider,
        'day': DayStatsDivider,
        'week': WeekStatsDivider,
        'month': MonthStatsDivider,
        'year': YearStatsDivider
    }
    return available.get(group_by, DEFAULT_GROUP_BY)


def get_people_change(queryset):
    change_there = 0
    for event in queryset:
        if event.event_type == CameraEventType.PERSON_ENTERED.value:
            change_there += 1
        elif event.event_type == CameraEventType.PERSON_LEFT.value:
            change_there -= 1
    return change_there


def secs_diff(begin: datetime, end: datetime):
    return (end - begin).total_seconds()


def calculate_on_interval(queryset, begin: datetime, end: datetime, start_value):
    full_len = secs_diff(begin, end)
    curr_value = start_value
    curr_begin = begin
    result = 0
    for event in queryset:
        if event.event_type == CameraEventType.PERSON_ENTERED.value:
            curr_value += 1
        elif event.event_type == CameraEventType.PERSON_LEFT.value:
            curr_value -= 1
        elif event.event_type == CameraEventType.OCCUPANCY_OVERRIDE.value:
            curr_value = event.event_value
        result += curr_value * secs_diff(curr_begin, event.timestamp)
        curr_begin = event.timestamp
    return float(result) / float(full_len)


class OccupancyStatsView(StatsView):
    serializer_class = OccupancyStatsSerializer

    def get_full_queryset(self, cafeteria_id):
        return CameraEvent.objects.filter(cafeteria_id=cafeteria_id)

    def timestamp_field_name(self):
        return 'timestamp'

    def init_value(self, before_queryset: QuerySet):
        # we keep (interval_finish_value, interval_weighted_average_value) as result in events
        overrides = before_queryset.filter(event_type=CameraEventType.OCCUPANCY_OVERRIDE.value)
        if len(overrides) == 0:
            change = get_people_change(before_queryset)
            return change, 0
        else:
            init_override_value = overrides.latest(self.timestamp_field_name()).event_value
            change = get_people_change(
                before_queryset.filter(timestamp__gt=overrides.latest(self.timestamp_field_name()).timestamp))
            return init_override_value + change, 0

    def next_count_value(self, count_value, curr_queryset: QuerySet, **kwargs):
        curr_overrides = curr_queryset.filter(event_type=CameraEventType.OCCUPANCY_OVERRIDE.value)
        last_finished, _ = count_value
        begin, end = kwargs.get('begin'), kwargs.get('end')
        weighted_average = calculate_on_interval(curr_queryset, begin, end, last_finished)
        if len(curr_overrides) == 0:
            change = get_people_change(curr_queryset)
            return last_finished + change, weighted_average
        else:
            last_override = curr_overrides.latest(self.timestamp_field_name())
            after_override = curr_queryset.filter(timestamp__gt=last_override.timestamp)
            override_value = last_override.event_value
            change_after = get_people_change(after_override)
            return override_value + change_after, weighted_average

    def map_to_result_objects(self, index, value, timestamp, cafeteria_pk):
        _, weighted_average = value
        capacity = Cafeteria.objects.get(id=cafeteria_pk).capacity
        return OccupancyStatsData(id=index,
                                  timestamp=timestamp,
                                  occupancy=weighted_average,
                                  occupancy_relative=(float(weighted_average) / float(capacity)))


class AverageDishReviewStatsView(StatsView):
    serializer_class = AverageDishReviewStatsSerializer

    def get_full_queryset(self, cafeteria_id):
        return FixedMenuOptionReview.objects.filter(option__cafeteria_id=cafeteria_id)

    def timestamp_field_name(self):
        return 'review_time'

    def init_value(self, before_queryset: QuerySet):
        all_stars = 0
        for review in before_queryset:
            all_stars += review.stars
        length = max(len(before_queryset), 1)
        return all_stars / length

    def next_count_value(self, count_value, curr_queryset: QuerySet, **kwargs):
        return self.init_value(curr_queryset)

    def map_to_result_objects(self, index, value, timestamp, cafeteria_pk):
        return AverageDishReviewStatsData(id=index, value=value, timestamp=timestamp)


AVAILABLE_STATS = [
    ('occupancy', OccupancyStatsView),
    ('avg_dish_review', AverageDishReviewStatsView),
]


# Admin authenticated with token uploads can inherit from this class
class AdminUploadView(views.APIView):
    parser_classes = [FileUploadParser]
    permission_classes = (IsAdminUser,)
    authentication_classes = (TokenAuthentication,)

    def __init__(self, save_file_path, **kwargs):
        super().__init__(**kwargs)
        self.file_path = save_file_path

    def put(self, request, *args, **kwargs):
        return handle_file_as_chunked(request, self.file_path)


class UploadArtifactsView(AdminUploadView):

    def __init__(self, **kwargs):
        super().__init__(path_join(settings.ARTIFACTS_ROOT, settings.ARTIFACT_NAME), **kwargs)


def handle_file_as_chunked(request, file_path):
    file_obj = request.data['file']
    with FileSystemStorage().open(file_path, 'wb+') as destination:
        for chunk in file_obj.chunks():
            destination.write(chunk)
    return Response(status=200)
