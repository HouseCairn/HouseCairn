from rest_framework.pagination import CursorPagination


class DefaultCursorPagination(CursorPagination):
    """Cursor pagination on creation time: stable while rows are added."""

    ordering = ("-created_at", "-id")
    page_size_query_param = "page_size"
    max_page_size = 200
