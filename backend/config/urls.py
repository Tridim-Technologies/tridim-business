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
from quotations.job_views import (
    job_assignment_create_view,
    job_assignment_remove_view,
    job_detail_view,
    job_note_create_view,
    jobs_view,
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
    path(
        "api/organizations/<uuid:organization_id>/jobs/",
        jobs_view,
        name="jobs",
    ),
    path(
        "api/organizations/<uuid:organization_id>/jobs/<int:job_id>/",
        job_detail_view,
        name="job-detail",
    ),
    path(
        "api/organizations/<uuid:organization_id>/jobs/<int:job_id>/assignments/",
        job_assignment_create_view,
        name="job-assignment-create",
    ),
    path(
        "api/organizations/<uuid:organization_id>/jobs/<int:job_id>/assignments/<int:assignment_id>/remove/",
        job_assignment_remove_view,
        name="job-assignment-remove",
    ),
    path(
        "api/organizations/<uuid:organization_id>/jobs/<int:job_id>/notes/",
        job_note_create_view,
        name="job-note-create",
    ),
]
