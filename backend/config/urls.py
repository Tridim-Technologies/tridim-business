from django.contrib import admin
from django.urls import path

from accounts.views import csrf_token, session_view, organizations_view
from customers.views import customer_detail_view, customers_view
from quotations.views import (
    quotation_detail_view,
    quotations_view,
    quotation_transition_view,
    quotation_revision_view,
)

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
    path(
        "api/organizations/<uuid:organization_id>/customers/<int:customer_id>/",
        customer_detail_view,
        name="customer-detail",
    ),
    path(
        "api/organizations/<uuid:organization_id>/quotations/",
        quotations_view,
        name="quotations",
    ),
    path(
        "api/organizations/<uuid:organization_id>/quotations/<uuid:quotation_id>/",
        quotation_detail_view,
        name="quotation-detail",
    ),
    path(
        "api/organizations/<uuid:organization_id>/quotations/<uuid:quotation_id>/transition/",
        quotation_transition_view,
        name="quotation-transition",
    ),
    path(
        "api/organizations/<uuid:organization_id>/quotations/<uuid:quotation_id>/revise/",
        quotation_revision_view,
        name="quotation-revise",
    ),
]
