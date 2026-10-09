from django.urls import path

from .views import public

urlpatterns = [
    path("", public.landing, name="landing"),
    path("<slug:slug>/", public.event_detail, name="event_detail"),
    path("<slug:slug>/me/", public.my_profile, name="my_profile"),
    path("<slug:slug>/items/<int:item_id>/", public.item_row, name="item_row"),
    path("<slug:slug>/items/<int:item_id>/claim/", public.claim, name="item_claim"),
    path("<slug:slug>/claims/<int:claim_id>/note/", public.claim_note, name="claim_note"),
    path("<slug:slug>/claims/<int:claim_id>/delete/", public.claim_delete, name="claim_delete"),
    path("<slug:slug>/categories/<int:category_id>/", public.category_row, name="category_row"),
    path("<slug:slug>/categories/<int:category_id>/custom-item/", public.custom_item, name="category_custom_item"),
]
