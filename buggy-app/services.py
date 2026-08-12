"""Business services for orders, discounts, and external price lookups."""

import asyncio

from models import Cart, CartItem, DiscountRequest, OrderSummary, Product
from utils import apply_percent_discount, find_cheapest_item


# In-memory catalog for demo purposes
PRODUCT_CATALOG: dict[int, Product] = {
    1: Product(id=1, name="Wireless Mouse", price=29.99, stock=50),
    2: Product(id=2, name="USB-C Hub", price=49.99, stock=30),
    3: Product(id=3, name="Mechanical Keyboard", price=89.99, stock=20),
}


def checkout_empty_cart(user_id: int) -> OrderSummary:
    """
    Checkout flow that builds an empty cart and tries to find the cheapest item.

    Triggers Bug 1 (IndexError) via find_cheapest_item on an empty cart.
    """
    cart = Cart(user_id=user_id, items=[])
    cheapest = find_cheapest_item(cart.items)
    total = sum(item.price * item.quantity for item in cart.items)
    return OrderSummary(
        user_id=user_id,
        cheapest_item=cheapest,
        total=total,
        final_total=total,
    )


def calculate_discounted_total(request: DiscountRequest) -> dict:
    """
    Calculate a discounted price.

    Triggers Bug 2 (TypeError): external API-style price arrives as a string,
    and apply_percent_discount tries arithmetic on it without conversion.
    """
    # Simulate an external pricing API that returns prices as strings
    raw_price = request.price if isinstance(request.price, str) else str(request.price)
    final_price = apply_percent_discount(raw_price, request.discount_percent)
    return {
        "original_price": raw_price,
        "discount_percent": request.discount_percent,
        "coupon_code": request.coupon_code,
        "final_price": final_price,
    }


async def fetch_product_price(product_id: int) -> float:
    """Simulate an async call to an external pricing service."""
    await asyncio.sleep(0.05)
    product = PRODUCT_CATALOG.get(product_id)
    if product is None:
        raise ValueError(f"Product {product_id} not found")
    return product.price


async def get_async_price_summary(product_id: int) -> dict:
    """
    Build a price summary using an async price fetch.

    BUG 3 — forgotten await: calls fetch_product_price without await, so
    `price` is a coroutine object instead of a float. Later formatting /
    arithmetic blows up (or returns a nonsensical coroutine in the response).
    """
    # Missing await — intentionally buggy
    price = fetch_product_price(product_id)
    tax = price * 0.08
    return {
        "product_id": product_id,
        "price": price,
        "tax": tax,
        "total": price + tax,
    }


def build_sample_cart(user_id: int) -> Cart:
    """Helper that returns a non-empty cart (for healthy reference paths)."""
    return Cart(
        user_id=user_id,
        items=[
            CartItem(product_id=1, name="Wireless Mouse", price=29.99, quantity=1),
            CartItem(product_id=2, name="USB-C Hub", price=49.99, quantity=2),
        ],
    )
