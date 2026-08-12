"""Domain models for a simple e-commerce order service."""

from pydantic import BaseModel, Field


class Product(BaseModel):
    id: int
    name: str
    price: float
    stock: int = 0


class CartItem(BaseModel):
    product_id: int
    name: str
    price: float
    quantity: int = Field(ge=1)


class Cart(BaseModel):
    user_id: int
    items: list[CartItem] = Field(default_factory=list)


class DiscountRequest(BaseModel):
    """Price may arrive as a string from an external pricing API."""

    price: str | float
    discount_percent: int = Field(ge=0, le=100)
    coupon_code: str | None = None


class OrderSummary(BaseModel):
    user_id: int
    cheapest_item: CartItem
    total: float
    discount_applied: float = 0.0
    final_total: float
