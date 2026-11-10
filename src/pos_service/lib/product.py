import asyncio
import typing

import aiofiles
import pydantic
import yaml

if typing.TYPE_CHECKING:
    from ..pos import POSService


class ProductMaster(pydantic.BaseModel):
    products: list["Product"]


class Product(pydantic.BaseModel):
    id: int
    name: str
    price: int


class ProductManager:
    def __init__(self, pos: "POSService", filename: str):
        self.pos = pos
        self.filename = filename
        self.master: ProductMaster | None = None
        self.products: list[Product] = []

    async def load(self):
        async with aiofiles.open(self.filename, "r", encoding="utf-8") as f:
            content = await f.read()
            data = yaml.safe_load(content)
            self.master = ProductMaster(**data)
            self.products = self.master.products

    def get_product(self, product_id: int) -> Product | None:
        for product in self.products:
            if product.id == product_id:
                return product
        return None
