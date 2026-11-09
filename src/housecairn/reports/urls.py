"""Web routes of reports, under /h/<home_id>/ (docs/adr/0010, 0047)."""

from django.urls import path

from housecairn.reports import views

app_name = "reports"

urlpatterns = [
    path("reports/", views.ReportListView.as_view(), name="list"),
    path("reports/new/", views.ReportCreateView.as_view(), name="create"),
    path("reports/<uuid:report_id>/", views.ReportDetailView.as_view(), name="detail"),
    path("reports/<uuid:report_id>/photo/", views.ReportPhotoView.as_view(), name="photo"),
    path(
        "reports/<uuid:report_id>/photo/thumbnail/",
        views.ReportThumbnailView.as_view(),
        name="photo-thumbnail",
    ),
    path("reports/<uuid:report_id>/task/", views.ReportToTaskView.as_view(), name="to-task"),
    path("reports/<uuid:report_id>/close/", views.ReportCloseView.as_view(), name="close"),
    path("reports/<uuid:report_id>/reopen/", views.ReportReopenView.as_view(), name="reopen"),
]
