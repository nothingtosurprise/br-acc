from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from icarus.dependencies import close_driver, init_driver
from icarus.middleware.cpf_masking import CPFMaskingMiddleware
from icarus.routers import entity, graph, meta, patterns, search


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.neo4j_driver = await init_driver()
    yield
    await close_driver()


app = FastAPI(
    title="ICARUS API",
    description="Brazilian public data anti-corruption graph tool",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CPFMaskingMiddleware)

app.include_router(meta.router)
app.include_router(entity.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(patterns.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
