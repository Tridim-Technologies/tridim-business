from django.contrib import admin
from django.urls import path

from accounts.views import csrf_token, session_view, organizations_view
from customers.views import customers_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/csrf/", csrf_token),
    path("api/session/", session_view),
    path("api/organizations/", organizations_view, name="organizations"),
    path(
        "api/organizations/<uuid:organization_id>/customers/",
        customers_view,
        name="customers",
    ),
]
