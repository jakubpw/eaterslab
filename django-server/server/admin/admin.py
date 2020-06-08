from django.apps import apps
from django.conf.urls import url
from django.contrib.admin import AdminSite
from django.contrib.admin import ModelAdmin
from django.db.models import Subquery, OuterRef, Max
from django.utils.html import format_html
from modeltranslation.admin import TranslationAdmin
from django.utils.translation import gettext_lazy as _

from .utils import is_admin
from .views import StatsView
from api.models import *

# To enforce registering translations
from api.translation import *


class MyAdminSite(AdminSite):
    site_header = _('EatersLab administration')
    site_title = _('EatersLab')
    index_title = _('Administration')
    index_template = 'admin/index_override.html'

    def get_urls(self):
        urls = super(MyAdminSite, self).get_urls()
        custom_urls = [
            url('stats/$', self.admin_view(StatsView.as_view(admin_site=self)), name='stats'),
        ]
        return urls + custom_urls


class CafeteriaAdmin(TranslationAdmin):
    list_display = ['name', 'address', 'owner', 'capacity', 'occupancy', 'opened_from', 'opened_to']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_admin(request.user):
            queryset = queryset.filter(owner=request.user)
        return queryset

    def get_form(self, request, obj=None, **kwargs):
        if not is_admin(request.user):
            self.exclude = ('owner', 'occupancy',)
        form = super().get_form(request, obj, **kwargs)
        return form

    def save_model(self, request, obj, form, change):
        if not obj.pk and not is_admin(request.user):
            obj.owner = request.user
            obj.occupancy = 0
        super().save_model(request, obj, form, change)


class CameraEventAdmin(ModelAdmin):
    list_display = ['id', 'cafeteria', 'camera', 'event_type', 'timestamp']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_admin(request.user):
            owned_cafeterias = Cafeteria.objects.filter(owner=request.user).values_list('id', flat=True)
            owned_cameras = Camera.objects.filter(cafeteria_id__in=set(owned_cafeterias)).values_list('id', flat=True)
            queryset = queryset.filter(camera_id__in=set(owned_cameras))
        return queryset


class CameraAdmin(ModelAdmin):
    list_display = ['id', 'name', 'cafeteria', 'state_with_icon', 'last_event']

    # Modify queryset to fetch last event timestamp (in _last_event column)
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_admin(request.user):
            owned_cafeterias = Cafeteria.objects.filter(owner=request.user).values_list('id', flat=True)
            queryset = queryset.filter(cafeteria_id__in=set(owned_cafeterias))

        last_event = CameraEvent.objects.filter(
            camera=OuterRef('pk')).values('camera').annotate(last_event=Max('timestamp')).values('last_event')
        queryset = queryset.annotate(_last_event=Subquery(last_event))
        return queryset

    # Extra field (state, with SVG icon) display
    def state_with_icon(self, obj):
        fill_color = '#000000'
        if obj.state == Camera.State.ONLINE:
            fill_color = '#00AA00'
        elif obj.state == Camera.State.OFFLINE:
            fill_color = '#CCCCCC'
        elif obj.state == Camera.State.LOST_CONNECTION:
            fill_color = '#FF9900'
        return format_html(
            '<svg viewbox="0 0 26 26" style="height: 0.8em; width: 0.8em;">'
            '<circle fill="{}" cx="13" cy="14" r="10"/></svg> {}',
            fill_color, obj.get_state_display()
        )

    # Extra field, last event timestamp
    def last_event(self, obj):
        return obj._last_event

    state_with_icon.short_description = _('State')
    last_event.short_description = _('Last event time')


class FixedMenuOptionAdmin(TranslationAdmin):
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_admin(request.user):
            owned_cafeterias = Cafeteria.objects.filter(owner=request.user).values_list('id', flat=True)
            queryset = queryset.filter(cafeteria_id__in=set(owned_cafeterias))
        return queryset


class FixedMenuOptionReviewAdmin(ModelAdmin):
    list_display = ['id', 'cafeteria', 'option', 'author_nick', 'rating', 'review_time']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_admin(request.user):
            owned_cafeterias = Cafeteria.objects.filter(owner=request.user).values_list('id', flat=True)
            owned_menu_options = FixedMenuOption.objects.filter(cafeteria_id__in=set(owned_cafeterias)).values_list('id', flat=True)
            queryset = queryset.filter(option__in=set(owned_menu_options))
        return queryset

    def rating(self, obj):
        return format_html("⭐" * obj.stars)

    def cafeteria(self, obj):
        return obj.option.cafeteria

    rating.short_description = _('rating')
    cafeteria.short_description = _('cafeteria')


admin_site = MyAdminSite(name='admin')
admin_site.register(Cafeteria, CafeteriaAdmin)
admin_site.register(CameraEvent, CameraEventAdmin)
admin_site.register(Camera, CameraAdmin)
admin_site.register(FixedMenuOption, FixedMenuOptionAdmin)
admin_site.register(FixedMenuOptionReview, FixedMenuOptionReviewAdmin)
