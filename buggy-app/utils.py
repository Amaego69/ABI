"""Utility helpers for cart and price calculations."""

from models import CartItem


def format_currency(amount: float) -> str:
    return f"${amount:.2f}"


def find_cheapest_item(items: list[CartItem]) -> CartItem:
    """
    Return the cheapest item in the cart.

    BUG 1 — IndexError: assumes the cart is never empty and indexes items[0]
    without a guard. Calling this with an empty list raises IndexError.
    """
    cheapest = items[0]
    for item in items[1:]:
        if item.price < cheapest.price:
            cheapest = item
    return cheapest


def apply_percent_discount(price, discount_percent: int) -> float:
    """
    Apply a percentage discount to a price.

    `price` may arrive as a string (as returned by an external pricing API),
    so it is converted to a float before performing arithmetic.
    """
    price = float(price)
    discount_amount = price * (discount_percent / 100)
    return price - discount_amount
