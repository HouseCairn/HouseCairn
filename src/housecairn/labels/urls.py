"""Web routes of QR labels, under /h/<home_id>/ (docs/adr/0010, 0047).

The address a sticker opens, `/l/<code>/` (route `label-open`), is in the root URLs: it
carries no home.
"""

from django.urls import path

from housecairn.labels import views

app_name = "labels"

urlpatterns = [
    path("labels/", views.LabelListView.as_view(), name="list"),
    path("labels/new/", views.LabelCreateView.as_view(), name="create"),
    path("labels/print/", views.LabelPrintView.as_view(), name="print"),
    path("labels/<uuid:label_id>/", views.LabelDetailView.as_view(), name="detail"),
    path(
        "labels/<uuid:label_id>/regenerate/",
        views.LabelRegenerateView.as_view(),
        name="regenerate",
    ),
    path("labels/<uuid:label_id>/revoke/", views.LabelRevokeView.as_view(), name="revoke"),
]
