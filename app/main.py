# from fastapi import FastAPI

# from app.api.transactions import router as transactions_router

# app = FastAPI(title="Transaction Webhook Service")


# @app.get("/")
# def health_check():
#     return {"status": "ok"}


# app.include_router(
#     transactions_router,
#     prefix="/v1",
#     tags=["Transactions"],
# )


from datetime import datetime, timezone

from fastapi import FastAPI

from app.api.transactions import router as transactions_router

app = FastAPI(title="Transaction Webhook Service")


@app.get("/")
def health_check():
    return {
        "status": "HEALTHY",
        "current_time": datetime.now(timezone.utc).isoformat(),
    }


app.include_router(
    transactions_router,
    prefix="/v1",
    tags=["Transactions"],
)
