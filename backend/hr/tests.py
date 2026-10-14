import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization
from .models import EmployeeProfile


class EmployeeDirectoryApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="hr-owner")
        self.employee = User.objects.create_user(username="hr-employee")
        self.other_employee = User.objects.create_user(username="other-employee")
        self.inactive_user = User.objects.create_user(
            username="inactive-employee", is_active=False
        )
        self.organization = Organization.objects.create(name="Alpha Services")
        self.other_organization = Organization.objects.create(name="Other Services")
        self.owner_membership = Membership.objects.create(
            user=self.owner,
            organization=self.organization,
            role=Membership.Role.OWNER,
        )
        self.employee_membership = Membership.objects.create(
            user=self.employee,
            organization=self.organization,
            role=Membership.Role.EMPLOYEE,
        )
        self.other_membership = Membership.objects.create(
            user=self.other_employee,
            organization=self.other_organization,
            role=Membership.Role.EMPLOYEE,
        )
        self.inactive_membership = Membership.objects.create(
            user=self.inactive_user,
            organization=self.organization,
            role=Membership.Role.EMPLOYEE,
        )
        self.url = reverse("employees", args=[self.organization.id])

    def payload(self, **overrides):
        return {
            "membership_id": self.employee_membership.id,
            "display_name": "  Ada   Njeri  ",
            "job_title": " Field   Technician ",
            "department": " Service   Delivery ",
            **overrides,
        }

    def post(self, payload, *, user=None):
        self.client.force_login(user or self.owner)
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_manager_creates_normalized_profile_for_member(self):
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["display_name"], "Ada Njeri")
        self.assertEqual(response.json()["job_title"], "Field Technician")
        self.assertEqual(response.json()["department"], "Service Delivery")
        self.assertNotIn("email", response.json())
        self.assertEqual(response.json()["username"], self.employee.username)
        profile = EmployeeProfile.objects.get(membership=self.employee_membership)
        self.assertEqual(profile.created_by, self.owner)

    def test_employees_can_read_active_directory_but_cannot_manage_profiles(self):
        profile = EmployeeProfile.objects.create(
            membership=self.employee_membership,
            display_name="Ada Njeri",
            created_by=self.owner,
        )
        self.client.force_login(self.employee)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [profile.id]
        )
        self.assertNotIn("members", response.json())
        self.assertNotIn("username", response.json()["results"][0])
        self.assertEqual(self.post(self.payload(), user=self.employee).status_code, 403)

    def test_inactive_profiles_are_hidden_by_default_and_restorable_by_manager(self):
        profile = EmployeeProfile.objects.create(
            membership=self.employee_membership,
            display_name="Ada Njeri",
            is_active=False,
            created_by=self.owner,
        )
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).json()["results"], [])
        response = self.client.get(f"{self.url}?status=all")
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [profile.id]
        )
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(f"{self.url}?status=all").status_code, 403)

    def test_profiles_for_deactivated_accounts_are_not_exposed(self):
        EmployeeProfile.objects.create(
            membership=self.inactive_membership,
            display_name="Inactive Staff",
            created_by=self.owner,
        )
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.json()["results"], [])
        self.assertNotIn(
            self.inactive_membership.id,
            [member["id"] for member in response.json()["members"]],
        )

    def test_manager_can_create_only_for_active_member_of_current_organization(self):
        foreign = self.post(self.payload(membership_id=self.other_membership.id))
        self.assertEqual(foreign.status_code, 400)
        inactive = self.post(self.payload(membership_id=self.inactive_membership.id))
        self.assertEqual(inactive.status_code, 400)
        self.assertEqual(EmployeeProfile.objects.count(), 0)

    def test_duplicate_profile_is_rejected(self):
        first = self.post(self.payload())
        second = self.post(self.payload())
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(EmployeeProfile.objects.count(), 1)

    def test_blank_display_name_is_rejected(self):
        response = self.post(self.payload(display_name="   "))
        self.assertEqual(response.status_code, 400)
        self.assertIn("display_name", response.json())

    def test_patch_is_tenant_scoped_and_manager_only(self):
        profile = EmployeeProfile.objects.create(
            membership=self.employee_membership,
            display_name="Ada Njeri",
            created_by=self.owner,
        )
        detail = reverse("employee-detail", args=[self.organization.id, profile.id])
        self.client.force_login(self.employee)
        denied = self.client.patch(
            detail,
            data=json.dumps({"job_title": "Technician"}),
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)
        self.client.force_login(self.owner)
        changed = self.client.patch(
            detail,
            data=json.dumps({"department": "  Service   Delivery  "}),
            content_type="application/json",
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["department"], "Service Delivery")
        foreign = self.client.patch(
            reverse("employee-detail", args=[self.other_organization.id, profile.id]),
            data=json.dumps({"job_title": "Technician"}),
            content_type="application/json",
        )
        self.assertEqual(foreign.status_code, 404)

    def test_membership_cannot_be_reassigned_and_inactive_users_are_not_listed(self):
        profile = EmployeeProfile.objects.create(
            membership=self.employee_membership,
            display_name="Ada Njeri",
            created_by=self.owner,
        )
        self.client.force_login(self.owner)
        detail = reverse("employee-detail", args=[self.organization.id, profile.id])
        response = self.client.patch(
            detail,
            data=json.dumps({"membership_id": self.owner_membership.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        choices = self.client.get(self.url).json()["members"]
        self.assertNotIn(self.inactive_membership.id, [item["id"] for item in choices])

    def test_unauthenticated_and_sales_roles_cannot_read_employee_directory(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        sales = get_user_model().objects.create_user(username="hr-sales")
        Membership.objects.create(
            user=sales, organization=self.organization, role=Membership.Role.SALES
        )
        self.client.force_login(sales)
        self.assertEqual(self.client.get(self.url).status_code, 403)
