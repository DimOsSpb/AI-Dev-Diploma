from app.routers import chat
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def root():
    return {"status": "ok"}


app.include_router(chat.router)
