"""Trigger endpoints that intentionally raise the three demo bugs."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from models import DiscountRequest
from services import (
    calculate_discounted_total,
    checkout_empty_cart,
    get_async_price_summary,
)

router = APIRouter(prefix="/trigger", tags=["triggers"])


class EmptyCartCheckoutBody(BaseModel):
    user_id: int = Field(default=1, ge=1)


class InvalidDiscountBody(BaseModel):
    price: str = Field(default="99.99", description="Price as string from external API")
    discount_percent: int = Field(default=10, ge=0, le=100)
    coupon_code: str | None = "WELCOME10"


@router.post("/empty-cart-checkout")
def trigger_empty_cart_checkout(body: EmptyCartCheckoutBody | None = None):
    """
    Trigger Bug 1 — IndexError.

    Checks out with an empty cart; find_cheapest_item accesses items[0].
    """
    payload = body or EmptyCartCheckoutBody()
    return checkout_empty_cart(payload.user_id)


@router.post("/invalid-discount-type")
def trigger_invalid_discount_type(body: InvalidDiscountBody | None = None):
    """
    Trigger Bug 2 — TypeError (str vs numeric arithmetic).

    Passes a string price into discount calculation without converting it.
    """
    payload = body or InvalidDiscountBody()
    request = DiscountRequest(
        price=payload.price,
        discount_percent=payload.discount_percent,
        coupon_code=payload.coupon_code,
    )
    return calculate_discounted_total(request)


@router.get("/async-price-fetch")
async def trigger_async_price_fetch(product_id: int = 1):
    """
    Trigger Bug 3 — forgotten await / coroutine object used as a number.

    Fetches a product price asynchronously but forgets to await the coroutine.
    """
    return await get_async_price_summary(product_id)
