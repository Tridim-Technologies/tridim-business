from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Membership, Organization
from customers.models import Customer


class OrganizationApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner", password="a-long-test-password"
        )
        self.finance = user_model.objects.create_user(
            username="finance", password="a-long-test-password"
        )
        self.org = Organization.objects.create(name="Alpha Services")
        self.other_org = Organization.objects.create(name="Other Services")
        Membership.objects.create(
            user=self.owner, organization=self.org, role=Membership.Role.OWNER
        )
        Membership.objects.create(
            user=self.finance, organization=self.org, role=Membership.Role.FINANCE
        )
        Customer.objects.create(
            name="Synthetic Example", organization=self.org, created_by=self.owner
        )

    def test_unauthenticated_customer_access_is_denied(self):
        response = self.client.get(reverse("customers", args=[self.org.pk]))
        self.assertEqual(response.status_code, 401)

    def test_session_login_returns_only_the_user_organizations(self):
        response = self.client.post(
            "/api/session/",
            data='{"username":"owner","password":"a-long-test-password"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["authenticated"], True)
        self.assertEqual(
            response.json()["organizations"],
            [{"id": str(self.org.pk), "name": "Alpha Services", "role": "owner"}],
        )

    def test_login_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        csrf_response = client.get("/api/csrf/")
        token = csrf_response.json()["csrfToken"]
        payload = '{"username":"owner","password":"a-long-test-password"}'
        denied = client.post(
            "/api/session/", data=payload, content_type="application/json"
        )
        self.assertEqual(denied.status_code, 403)
        accepted = client.post(
            "/api/session/",
            data=payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 200)

    def test_member_sees_only_customers_in_their_organization(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customers", args=[self.org.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["name"] for row in response.json()["results"]], ["Synthetic Example"]
        )

    def test_non_member_cannot_probe_another_organization(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customers", args=[self.other_org.pk]))
        self.assertEqual(response.status_code, 404)

    def test_employee_cannot_list_the_customer_directory(self):
        employee = get_user_model().objects.create_user(
            username="employee", password="a-long-test-password"
        )
        Membership.objects.create(
            user=employee, organization=self.org, role=Membership.Role.EMPLOYEE
        )
        self.client.force_login(self.finance)
        self.assertEqual(
            self.client.get(reverse("customers", args=[self.org.pk])).status_code, 200
        )
        self.client.force_login(employee)
        response = self.client.get(reverse("customers", args=[self.org.pk]))
        self.assertEqual(response.status_code, 403)

    def test_finance_role_cannot_create_customer(self):
        self.client.force_login(self.finance)
        response = self.client.post(
            reverse("customers", args=[self.org.pk]),
            data='{"name":"Blocked Example"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Customer.objects.filter(name="Blocked Example").exists())

    def test_sales_role_can_create_customer_in_organization(self):
        sales = get_user_model().objects.create_user(
            username="sales", password="a-long-test-password"
        )
        Membership.objects.create(
            user=sales, organization=self.org, role=Membership.Role.SALES
        )
        self.client.force_login(sales)
        response = self.client.post(
            reverse("customers", args=[self.org.pk]),
            data='{"name":"New Synthetic Customer"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        customer = Customer.objects.get(name="New Synthetic Customer")
        self.assertEqual(customer.organization, self.org)
        self.assertEqual(customer.created_by, sales)

    def test_invalid_email_is_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("customers", args=[self.org.pk]),
            data='{"name":"New Customer","email":"not-an-email"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json())

    def test_duplicate_customer_name_is_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            f"/api/organizations/{self.org.pk}/customers/",
            data='{"name":"Synthetic Example"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["name"][0])

    def test_non_object_json_is_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("customers", args=[self.org.pk]),
            data='["not", "an", "object"]',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
