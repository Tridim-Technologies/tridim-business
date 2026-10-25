import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization
from .models import Product, StorefrontProfile


class StorefrontTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="storefront-owner")
        self.admin = user_model.objects.create_user(username="storefront-admin")
        self.operations = user_model.objects.create_user(username="storefront-ops")
        self.employee = user_model.objects.create_user(username="storefront-employee")
        self.organization = Organization.objects.create(name="Storefront Org")
        self.other_organization = Organization.objects.create(name="Other Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.admin, Membership.Role.ADMIN),
            (self.operations, Membership.Role.OPERATIONS),
            (self.employee, Membership.Role.EMPLOYEE),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role
            )
        self.profile_url = reverse("storefront-profile", args=[self.organization.pk])
        self.product_url = reverse(
            "inventory-products", args=[self.organization.pk]
        )
        self.client.force_login(self.owner)

    def request_json(self, method, url, data, *, user=None):
        if user:
            self.client.force_login(user)
        return getattr(self.client, method)(
            url, data=json.dumps(data), content_type="application/json"
        )

    def configure_storefront(self, *, slug="sample-shop", is_published=True, user=None):
        return self.request_json(
            "put",
            self.profile_url,
            {
                "slug": slug,
                "display_name": "Sample Shop",
                "currency": "KES",
                "is_published": is_published,
            },
            user=user,
        )

    def make_product(
        self,
        *,
        sku,
        name,
        is_published=True,
        is_active=True,
        organization=None,
    ):
        return Product.objects.create(
            organization=organization or self.organization,
            sku=sku,
            name=name,
            base_unit="ea",
            storefront_description="Public description",
            storefront_price="12.50",
            is_published=is_published,
            is_active=is_active,
            created_by=self.owner,
        )

    def test_only_owner_and_admin_can_manage_profile(self):
        self.assertEqual(self.configure_storefront().status_code, 200)
        self.assertEqual(
            self.configure_storefront(
                slug="admin-shop", is_published=False, user=self.admin
            ).status_code,
            200,
        )
        self.assertEqual(
            self.configure_storefront(slug="ops-shop", user=self.operations).status_code,
            403,
        )
        self.assertEqual(self.client.get(self.profile_url).status_code, 200)
        self.assertEqual(
            self.client.get(self.profile_url).json()["profile"]["slug"],
            "admin-shop",
        )
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.profile_url).status_code, 403)

    def test_public_catalog_is_read_only_tenant_scoped_and_minimal(self):
        self.assertEqual(self.configure_storefront().status_code, 200)
        public_product = self.make_product(sku="SECRET-SKU", name="Listed item")
        self.make_product(sku="HIDDEN", name="Unpublished item", is_published=False)
        self.make_product(sku="INACTIVE", name="Inactive item", is_active=False)
        self.make_product(
            sku="OTHER-TENANT",
            name="Other tenant item",
            organization=self.other_organization,
        )

        self.client.logout()
        response = self.client.get(reverse("public-storefront", args=["sample-shop"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        body = response.json()
        self.assertEqual(
            body["store"],
            {"slug": "sample-shop", "name": "Sample Shop", "currency": "KES"},
        )
        self.assertEqual(
            body["products"],
            [
                {
                    "name": public_product.name,
                    "description": "Public description",
                    "unit": "ea",
                    "price": "12.50",
                }
            ],
        )
        self.assertNotIn("SECRET-SKU", response.content.decode())
        self.assertNotIn("OTHER-TENANT", response.content.decode())

    def test_unpublished_profile_is_not_public(self):
        self.assertEqual(
            self.configure_storefront(is_published=False).status_code, 200
        )
        response = self.client.get(reverse("public-storefront", args=["sample-shop"]))
        self.assertEqual(response.status_code, 404)

    def test_storefront_slug_is_unique_without_case_sensitivity(self):
        self.assertEqual(self.configure_storefront().status_code, 200)
        other_user = get_user_model().objects.create_user(username="other-owner")
        Membership.objects.create(
            organization=self.other_organization,
            user=other_user,
            role=Membership.Role.OWNER,
        )
        response = self.request_json(
            "put",
            reverse("storefront-profile", args=[self.other_organization.pk]),
            {
                "slug": "sample-shop",
                "display_name": "Other Shop",
                "currency": "KES",
                "is_published": True,
            },
            user=other_user,
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(
            StorefrontProfile.objects.filter(
                organization=self.other_organization
            ).exists()
        )

    def test_only_managers_can_publish_products_and_listing_requires_content(self):
        payload = {
            "sku": "NEW-ITEM",
            "name": "New item",
            "base_unit": "ea",
            "storefront_description": "Public description",
            "storefront_price": "10.25",
            "is_published": True,
        }
        response = self.request_json(
            "post", self.product_url, payload, user=self.operations
        )
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.owner)
        incomplete = self.request_json(
            "post",
            self.product_url,
            {**payload, "storefront_description": "", "is_published": True},
        )
        self.assertEqual(incomplete.status_code, 400)

        created = self.request_json("post", self.product_url, payload)
        self.assertEqual(created.status_code, 201, created.content)
        product_id = created.json()["id"]
        detail_url = reverse(
            "inventory-product-detail", args=[self.organization.pk, product_id]
        )
        forbidden = self.request_json(
            "patch", detail_url, {"is_published": False}, user=self.operations
        )
        self.assertEqual(forbidden.status_code, 403)
