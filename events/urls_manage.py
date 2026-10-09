"""Admin-only URLs, mounted under /manage/."""

from django.urls import path

from .views import manage

urlpatterns = [
    path("logout/", manage.logout, name="manage_logout"),
    path("guest-view/", manage.guest_view_start, name="manage_guest_view"),
    path("guest-view/exit/", manage.guest_view_exit, name="manage_guest_view_exit"),
    path("site/", manage.site_settings, name="manage_site_settings"),
    path("new/", manage.event_new, name="manage_event_new"),
    path("<slug:slug>/settings/", manage.event_settings, name="manage_event_settings"),
    path("<slug:slug>/delete/", manage.event_delete, name="manage_event_delete"),
    path("<slug:slug>/responses/", manage.event_responses, name="manage_event_responses"),
    # Custom fields
    path("<slug:slug>/fields/add/", manage.field_add, name="manage_field_add"),
    path("<slug:slug>/fields/<int:pk>/edit/", manage.field_edit, name="manage_field_edit"),
    path("<slug:slug>/fields/<int:pk>/delete/", manage.field_delete, name="manage_field_delete"),
    path("<slug:slug>/fields/<int:pk>/move/<str:direction>/", manage.field_move, name="manage_field_move"),
    path("<slug:slug>/fields/<int:pk>/toggle/<str:attr>/", manage.field_toggle, name="manage_field_toggle"),
    # Categories
    path("<slug:slug>/categories/add/", manage.category_add, name="manage_category_add"),
    path("<slug:slug>/categories/<int:pk>/edit/", manage.category_edit, name="manage_category_edit"),
    path("<slug:slug>/categories/<int:pk>/delete/", manage.category_delete, name="manage_category_delete"),
    path("<slug:slug>/categories/<int:pk>/move/<str:direction>/", manage.category_move, name="manage_category_move"),
    path(
        "<slug:slug>/categories/<int:pk>/toggle-custom/",
        manage.category_toggle_custom,
        name="manage_category_toggle_custom",
    ),
    path("<slug:slug>/categories/<int:category_pk>/items/add/", manage.item_add, name="manage_item_add"),
    # Items
    path("<slug:slug>/items/<int:pk>/edit/", manage.item_edit, name="manage_item_edit"),
    path("<slug:slug>/items/<int:pk>/delete/", manage.item_delete, name="manage_item_delete"),
    path("<slug:slug>/items/<int:pk>/move/<str:direction>/", manage.item_move, name="manage_item_move"),
    # Responses
    path("<slug:slug>/attendees/<int:pk>/edit/", manage.attendee_edit, name="manage_attendee_edit"),
    path("<slug:slug>/attendees/<int:pk>/delete/", manage.attendee_delete, name="manage_attendee_delete"),
    path("<slug:slug>/claims/<int:pk>/note/", manage.claim_note, name="manage_claim_note"),
    path("<slug:slug>/claims/<int:pk>/delete/", manage.claim_delete, name="manage_claim_delete"),
]
