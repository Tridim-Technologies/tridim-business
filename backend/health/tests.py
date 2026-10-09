from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase
from django.urls import reverse


class HealthEndpointTests(SimpleTestCase):
    def test_liveness_does_not_check_database(self):
        with patch("health.views.connections") as connections:
            response = self.client.get(reverse("health-live"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        connections.__getitem__.assert_not_called()

    def test_readiness_returns_success_when_database_is_reachable(self):
        with patch("health.views.connections") as connections:
            response = self.client.get(reverse("health-ready"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        connections.__getitem__.return_value.ensure_connection.assert_called_once_with()

    def test_readiness_returns_generic_unavailable_when_database_fails(self):
        with patch("health.views.connections") as connections:
            connections.__getitem__.return_value.ensure_connection.side_effect = (
                OperationalError("sensitive database connection detail")
            )
            response = self.client.get(reverse("health-ready"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"unavailable")
        self.assertNotIn(b"sensitive", response.content)

    def test_health_endpoints_reject_non_get_methods(self):
        self.assertEqual(self.client.post(reverse("health-live")).status_code, 405)
        self.assertEqual(self.client.post(reverse("health-ready")).status_code, 405)
