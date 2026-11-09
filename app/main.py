
from fastapi import FastAPI

app = FastAPI(
    title="My First FastAPI",
    description="My Backend API",
    version="1.0.0"
)

@app.get("/")
def home():
    return {
        "status": "success",
        "message": "Hello World from FastAPI!"
    }

@app.get("/about")
def about():
    return {
        "status": "success",
        "message": "This is my first FastAPI project"
    }

@app.get("/users")
def get_users():
    return {
        "users": [
            {"id": 1, "name": "Budi"},
            {"id": 2, "name": "Andi"}
        ]
    }
