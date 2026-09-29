from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Edge Cases API")


class Item(BaseModel):
    id: int
    name: str


@app.get("/items")
def list_items():
    # совпадает со спекой
    return [{"id": 1, "name": "a"}]


@app.get("/typed")
def typed():
    # расхождение по типу: спека говорит integer, код отдаёт str
    return {"count": "42"}


@app.get("/extra")
def extra():
    # ghost_endpoint: есть в коде, нет в спеке
    return {"ok": True}
# /legacy в коде отсутствует → должно быть missing_endpoint