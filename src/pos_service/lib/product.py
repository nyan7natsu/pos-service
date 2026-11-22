import typing

import aiofiles
import pydantic
import yaml

if typing.TYPE_CHECKING:
    from ..pos import POSService


class ProductMaster(pydantic.BaseModel):
    products: list["Product"]
    discounts: list["Discounts"] = []


class ProductItem(pydantic.BaseModel):
    product_name: str
    quantity: int

class Product(pydantic.BaseModel):
    id: int
    name: str
    price: int
    category: str = ""
    enabled: bool = True
    items: list[ProductItem] = []


class DiscountTake(pydantic.BaseModel):
    category: str
    quantity: int


class Discounts(pydantic.BaseModel):
    name: str
    discount: int
    enabled: bool = True
    take: list[DiscountTake] = []

class ProductManager:
    def __init__(self, pos: "POSService", filename: str):
        self.pos = pos
        self.filename = filename
        self.master: ProductMaster | None = None
        self.products: list[Product] = []
        self.discounts: list[Discounts] = []

    async def load(self):
        async with aiofiles.open(self.filename, "r", encoding="utf-8") as f:
            content = await f.read()
            data = yaml.safe_load(content)
            self.master = ProductMaster(**data)
            self.products = self.master.products
            self.discounts = self.master.discounts

    def get_product(self, product_id: int) -> Product | None:
        for product in self.products:
            if product.id == product_id:
                return product
        return None
