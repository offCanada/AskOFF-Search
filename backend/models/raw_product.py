from typing import Optional

from pydantic import BaseModel


class RawProduct(BaseModel):
    code: str
    product_name: str
    brands: str
    categories: str
    ingredients_text: str
    nutriments: dict
    nutriscore_grade: Optional[str] = None
    nova_group: Optional[int] = None
    ecoscore_grade: Optional[str] = None
    completeness: float = 0.0
    image_url: Optional[str] = None

