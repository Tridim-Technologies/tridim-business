from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_GET

from accounts.models import Membership, Organization

from .models import Product, StorefrontProfile
from .serializers import StorefrontProfileSerializer, StorefrontProfileWriteSerializer
from .views import _membership, _payload


MANAGERS = {Membership.Role.OWNER, Membership.Role.ADMIN}


@require_http_methods(["GET", "PUT"])
def storefront_profile_view(request, organization_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error

    if request.method == "GET":
        profile = StorefrontProfile.objects.filter(
            organization_id=organization_id
        ).first()
        return JsonResponse(
            {"profile": StorefrontProfileSerializer(profile).data if profile else None}
        )

    if membership.role not in MANAGERS:
        return JsonResponse(
            {"detail": "Only organization owners and admins can manage the storefront."},
            status=403,
        )
    values, error = _payload(request, StorefrontProfileWriteSerializer)
    if error:
        return error

    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            profile = StorefrontProfile.objects.filter(
                organization_id=organization_id
            ).first()
            duplicate = StorefrontProfile.objects.filter(
                slug__iexact=values["slug"]
            )
            if profile:
                duplicate = duplicate.exclude(pk=profile.pk)
            if duplicate.exists():
                return JsonResponse(
                    {"slug": ["This storefront URL is already in use."]}, status=409
                )
            if profile:
                for field, value in values.items():
                    setattr(profile, field, value)
                profile.save(update_fields=[*values, "updated_at"])
            else:
                profile = StorefrontProfile.objects.create(
                    organization_id=organization_id, **values
                )
    except IntegrityError:
        return JsonResponse(
            {"slug": ["This storefront URL is already in use."]}, status=409
        )
    return JsonResponse({"profile": StorefrontProfileSerializer(profile).data})


@require_GET
def public_storefront_view(request, slug):
    profile = (
        StorefrontProfile.objects.select_related("organization")
        .filter(slug__iexact=slug, is_published=True)
        .first()
    )
    if profile is None:
        return JsonResponse({"detail": "Storefront not found."}, status=404)

    products = Product.objects.filter(
        organization_id=profile.organization_id,
        is_active=True,
        is_published=True,
        storefront_price__isnull=False,
    ).exclude(storefront_description="")
    response = JsonResponse(
        {
            "store": {
                "slug": profile.slug,
                "name": profile.display_name,
                "currency": profile.currency,
            },
            "products": [
                {
                    "name": product.name,
                    "description": product.storefront_description,
                    "unit": product.base_unit,
                    "price": format(product.storefront_price, ".2f"),
                }
                for product in products
            ],
        }
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
