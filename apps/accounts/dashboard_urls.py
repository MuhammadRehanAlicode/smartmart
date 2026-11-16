from django.urls import path

from apps.reports.views import DashboardSearchView, DashboardView

from . import views

app_name = "dashboard"
urlpatterns = [
    path("", DashboardView.as_view(), name="home"),
    path("search/", DashboardSearchView.as_view(), name="search"),
    path("staff/", views.StaffListView.as_view(), name="staff-list"),
    path("staff/new/", views.StaffCreateView.as_view(), name="staff-create"),
    path("staff/<int:pk>/edit/", views.StaffEditView.as_view(), name="staff-edit"),
]
