from fastapi import FastAPI

app = FastAPI()
_received: list[dict] = []


@app.post("/ingest")
def ingest(rows: list[dict]):
    _received.extend(rows)
    return {"received": len(rows), "total": len(_received), "sample": rows[0] if rows else None}


@app.get("/count")
def count():
    return {"total": len(_received)}
