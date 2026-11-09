"""Web routes of projects, under /h/<home_id>/ (docs/adr/0010, 0050)."""

from django.urls import path

from housecairn.projects import views

app_name = "projects"

urlpatterns = [
    path("projects/", views.ProjectListView.as_view(), name="list"),
    path("projects/new/", views.ProjectCreateView.as_view(), name="create"),
    path("projects/compare/", views.CompareView.as_view(), name="compare"),
    path("projects/envelope/", views.EnvelopeView.as_view(), name="envelope"),
    path("projects/<uuid:project_id>/", views.ProjectDetailView.as_view(), name="detail"),
    path("projects/<uuid:project_id>/edit/", views.ProjectEditView.as_view(), name="edit"),
    path("projects/<uuid:project_id>/delete/", views.ProjectDeleteView.as_view(), name="delete"),
    path("projects/<uuid:project_id>/tasks/new/", views.TaskAddView.as_view(), name="task-add"),
    path(
        "projects/<uuid:project_id>/tasks/attach/",
        views.TaskAttachView.as_view(),
        name="task-attach",
    ),
    path(
        "projects/<uuid:project_id>/tasks/<uuid:task_id>/remove/",
        views.TaskDetachView.as_view(),
        name="task-detach",
    ),
    path(
        "projects/<uuid:project_id>/lines/new/", views.LineCreateView.as_view(), name="line-create"
    ),
    path("projects/lines/<uuid:line_id>/edit/", views.LineEditView.as_view(), name="line-edit"),
    path(
        "projects/lines/<uuid:line_id>/delete/", views.LineDeleteView.as_view(), name="line-delete"
    ),
    path(
        "projects/<uuid:project_id>/quotes/new/",
        views.QuoteCreateView.as_view(),
        name="quote-create",
    ),
    path("projects/quotes/<uuid:quote_id>/edit/", views.QuoteEditView.as_view(), name="quote-edit"),
    path(
        "projects/quotes/<uuid:quote_id>/accept/",
        views.QuoteAcceptView.as_view(),
        name="quote-accept",
    ),
    path(
        "projects/quotes/<uuid:quote_id>/status/",
        views.QuoteStatusView.as_view(),
        name="quote-status",
    ),
    path(
        "projects/quotes/<uuid:quote_id>/delete/",
        views.QuoteDeleteView.as_view(),
        name="quote-delete",
    ),
    path("projects/<uuid:project_id>/photos/new/", views.FileAddView.as_view(), name="file-add"),
    path("projects/files/<uuid:file_id>/", views.FileView.as_view(), name="file"),
    path(
        "projects/files/<uuid:file_id>/thumbnail/",
        views.ThumbnailView.as_view(),
        name="file-thumbnail",
    ),
    path(
        "projects/files/<uuid:file_id>/delete/", views.FileDeleteView.as_view(), name="file-delete"
    ),
]
