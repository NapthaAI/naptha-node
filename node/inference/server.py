# inference/litellm/server.py
import logging
import traceback
from typing import Optional
import os
import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from node.schemas import ChatCompletionRequest, CompletionRequest, EmbeddingsRequest

load_dotenv()

# Group all endpoints under "inference" in the Swagger docs
router = APIRouter(prefix="/inference", tags=["inference"])

LITELLM_HTTP_TIMEOUT = 60 * 5
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY")
if not LITELLM_MASTER_KEY:
    raise Exception("Missing LITELLM_MASTER_KEY for authentication")
LITELLM_URL = "http://litellm:4000" if os.getenv("LAUNCH_DOCKER") == "true" else "http://localhost:4000"


@router.get("/models", summary="List Models")
async def models_endpoint(return_wildcard_routes: Optional[bool] = Query(False, alias="return_wildcard_routes")):
    logging.info("Received models list request")
    try:
        params = {"return_wildcard_routes": return_wildcard_routes}
        async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{LITELLM_URL}/models",
                params=params,
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"}
            )
            logging.info(f"LiteLLM models response: {response.json()}")
            return response.json()
    except httpx.ReadTimeout:
        logging.error("Request to LiteLLM timed out")
        raise HTTPException(status_code=504, detail="Request to LiteLLM timed out")
    except Exception as e:
        logging.error(f"Error in models endpoint: {str(e)}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/completions", summary="Chat Completion")
async def chat_completions_endpoint(
    request_body: ChatCompletionRequest,
    model: str = Query(None, description="Model")
):
    logging.info("Received chat completions request")
    payload = request_body.model_dump(exclude_none=True)
    if model:
        payload["model"] = model

    try:
        if payload.get("stream", False):
            async def stream_generator():
                async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
                    async with client.stream(
                        "POST",
                        f"{LITELLM_URL}/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"}
                    ) as response:
                        async for chunk in response.aiter_bytes():
                            # Stream raw output from LiteLLM
                            yield chunk

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream"
            )

        async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{LITELLM_URL}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"}
            )
            logging.info(f"LiteLLM response: {response.json()}")
            return response.json()

    except httpx.ReadTimeout:
        logging.error("Request to LiteLLM timed out")
        raise HTTPException(status_code=504, detail="Request to LiteLLM timed out")
    except Exception as e:
        logging.error(f"Error in chat completions endpoint: {str(e)}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/completions", summary="Completion")
async def completions_endpoint(
    request_body: CompletionRequest,
    model: str = Query(None, description="Model")
):
    logging.info("Received completions request")
    payload = request_body.model_dump(exclude_none=True)
    if model:
        payload["model"] = model

    try:
        if payload.get("stream", False):
            async def stream_generator():
                async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
                    async with client.stream(
                        "POST",
                        f"{LITELLM_URL}/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"}
                    ) as response:
                        async for chunk in response.aiter_bytes():
                            yield chunk

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream"
            )

        async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{LITELLM_URL}/completions",
                json=payload,
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"}
            )
            logging.info(f"LiteLLM completions response: {response.json()}")
            return response.json()

    except httpx.ReadTimeout:
        logging.error("Request to LiteLLM timed out")
        raise HTTPException(status_code=504, detail="Request to LiteLLM timed out")
    except Exception as e:
        logging.error(f"Error in completions endpoint: {str(e)}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embeddings", summary="Embeddings")
async def embeddings_endpoint(
    request_body: EmbeddingsRequest,
    model: Optional[str] = Query(None, description="Model")
):
    logging.info("Received embeddings request")
    payload = request_body.model_dump(exclude_none=True)
    if model is not None:
        payload["model"] = model
    try:
        async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{LITELLM_URL}/embeddings",
                json=payload,
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"}
            )
            logging.info(f"LiteLLM embeddings response: {response.json()}")
            return response.json()
    except httpx.ReadTimeout:
        logging.error("Request to LiteLLM timed out")
        raise HTTPException(status_code=504, detail="Request to LiteLLM timed out")
    except Exception as e:
        logging.error(f"Error in embeddings endpoint: {str(e)}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
