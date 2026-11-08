"""Web routes of tasks and occurrences, under /h/<home_id>/ (docs/adr/0010, 0031)."""

from django.urls import path

from housecairn.tasks import views

app_name = "tasks"

urlpatterns = [
    path("tasks/", views.TaskListView.as_view(), name="list"),
    path("tasks/new/", views.TaskCreateView.as_view(), name="create"),
    path("tasks/<uuid:task_id>/", views.TaskDetailView.as_view(), name="detail"),
    path("tasks/<uuid:task_id>/edit/", views.TaskEditView.as_view(), name="edit"),
    path("tasks/<uuid:task_id>/delete/", views.TaskDeleteView.as_view(), name="delete"),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/complete/",
        views.OccurrenceCompleteView.as_view(),
        name="complete",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/undo/",
        views.OccurrenceUndoView.as_view(),
        name="undo",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/skip/",
        views.OccurrenceSkipView.as_view(),
        name="skip",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/postpone/",
        views.OccurrencePostponeView.as_view(),
        name="postpone",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/edit/",
        views.OccurrenceEditView.as_view(),
        name="occurrence-edit",
    ),
]
