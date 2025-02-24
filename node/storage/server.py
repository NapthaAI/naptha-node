from fastapi import APIRouter, HTTPException, Body, Query, Path, File, UploadFile, Response, Form   
from typing import Optional, Dict, Any, Union, List
import logging
import json
import traceback
from fastapi.responses import FileResponse
from pydantic import ValidationError
from node.storage.storage_provider import (
    DatabaseStorageProvider,
    FilesystemStorageProvider,
    IPFSStorageProvider
)
from node.storage.schemas import StorageLocation, StorageType, DatabaseReadOptions, IPFSOptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"]) 
    
@router.post("/{storage_type}/create/{path:path}")
async def create_storage_object(
    storage_type: StorageType,
    path: str = Path(..., description="Storage path/identifier"),
    file: Optional[UploadFile] = File(None),
    request_data: Optional[str] = Form(None, alias="data")  # Use alias to match form field name
):
    """Create new storage objects (table, file, or IPFS content)"""
    request_data = json.loads(request_data) if request_data else None

    logger.debug(f"Received data: {request_data}")
    logger.debug(f"Received file: {file}")

    location = StorageLocation(storage_type=storage_type, path=path)
    
    if storage_type == StorageType.DATABASE:
        storage_provider = DatabaseStorageProvider()
        if not request_data:
            raise HTTPException(400, "Database storage requires schema data")
        return await storage_provider.create(location, request_data, {"type": "table"})
        
    elif storage_type == StorageType.FILESYSTEM:
        storage_provider = FilesystemStorageProvider()
        if not file:
            raise HTTPException(400, "Filesystem storage requires file upload")
        return await storage_provider.create(location, file, {"type": "file"})
        
    elif storage_type == StorageType.IPFS:
        storage_provider = IPFSStorageProvider()
        if not file:
            raise HTTPException(400, "IPFS storage requires file upload")
            
        ipfs_options = IPFSOptions(**(request_data or {}))
        return await storage_provider.create(location, file, ipfs_options)
        
    raise HTTPException(400, "Invalid storage type")

@router.get("/{storage_type}/read/{path:path}")
async def read_storage_object(
    storage_type: StorageType,
    path: str = Path(..., description="Storage path/identifier"),
    options: Optional[str] = Query(None, description="JSON string of options"),
):
    """Read from storage (query DB, read file, or fetch IPFS content)"""

    # Provider selection
    if storage_type not in StorageType:
        raise HTTPException(400, "Invalid storage type")
        
    providers = {
        StorageType.DATABASE: DatabaseStorageProvider,
        StorageType.FILESYSTEM: FilesystemStorageProvider,
        StorageType.IPFS: IPFSStorageProvider
    }
    storage_provider = providers[storage_type]()
    location = StorageLocation(storage_type=storage_type, path=path)
    
    try:
        if storage_type == StorageType.DATABASE:
            parsed_options = json.loads(options) if options else {}
            db_options = DatabaseReadOptions(**parsed_options)
            result = await storage_provider.read(location, db_options)
            return result.data
            
        elif storage_type == StorageType.FILESYSTEM:
            result = await storage_provider.read(location, None)
            if isinstance(result.data, dict) and "path" in result.data:
                return FileResponse(
                    path=result.data["path"],
                    media_type=result.data.get("media_type", "application/octet-stream"),
                    filename=result.data.get("filename"),
                    headers=result.data.get("headers", {})
                )
            else:
                return Response(
                    content=result.data,
                    media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename={path.split('/')[-1]}"}
                )
                
        elif storage_type == StorageType.IPFS:
            try:
                parsed_options = json.loads(options) if options else {}
                ipfs_options = IPFSOptions(**parsed_options)
            except json.JSONDecodeError:
                raise HTTPException(400, "Invalid options JSON format")
            except ValidationError:
                raise HTTPException(400, "Invalid IPFS options")
                
            result = await storage_provider.read(location, ipfs_options.dict())
            
            # Handle both file and directory responses
            if result.data.get("is_directory"):
                return Response(
                    content=result.data["content"],
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": f"attachment; filename={result.data['filename']}"
                    }
                )
            else:
                return Response(
                    content=result.data["content"],
                    media_type=result.data.get("media_type", "application/octet-stream"),
                    headers={
                        "Content-Disposition": f"attachment; filename={result.data['filename']}"
                    }
                )
            
    except FileNotFoundError:
        raise HTTPException(404, "File or directory not found")
    except PermissionError:
        raise HTTPException(403, "Permission denied accessing file")
    except Exception as e:
        logger.error(f"Storage read error: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{storage_type}/delete/{path:path}")
async def delete_storage_object(
    storage_type: StorageType,
    path: str = Path(..., description="Storage path/identifier"),
    condition: Optional[str] = Query(None, description="Delete condition for DB (JSON string)"),
    options: Optional[str] = Query(None, description="Storage-specific options (JSON string)")
):
    """Delete storage objects"""
    if storage_type == StorageType.DATABASE:
        storage_provider = DatabaseStorageProvider()
    elif storage_type == StorageType.FILESYSTEM:
        storage_provider = FilesystemStorageProvider()
    elif storage_type == StorageType.IPFS:
        storage_provider = IPFSStorageProvider()
    else:
        raise HTTPException(400, "Invalid storage type")

    location = StorageLocation(storage_type=storage_type, path=path)
    
    try:
        condition_dict = json.loads(condition) if condition else None
        options_dict = json.loads(options) if options else None

        if storage_type == StorageType.DATABASE and condition_dict:
            options_dict = {"condition": condition_dict, **(options_dict or {})}
        return await storage_provider.delete(location, options_dict)  # Removed storage_type argument
    
    except Exception as e:
        logger.error(f"Storage delete error: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{storage_type}/list/{path:path}")
async def list_storage_objects(
    storage_type: StorageType,
    path: str = Path(..., description="Storage path/identifier"),
    options: Optional[str] = Query(None, description="JSON string of options"),
):
    """List storage objects (DB tables/rows, directory contents, IPFS directory)"""

    if storage_type == StorageType.DATABASE:
        storage_provider = DatabaseStorageProvider()
    elif storage_type == StorageType.FILESYSTEM:
        storage_provider = FilesystemStorageProvider()
    elif storage_type == StorageType.IPFS:
        storage_provider = IPFSStorageProvider()
    else:
        raise HTTPException(400, "Invalid storage type")

    location = StorageLocation(storage_type=storage_type, path=path)
    
    try:
        parsed_options = json.loads(options) if options else {}
        
        if storage_type == StorageType.DATABASE:
            options_obj = DatabaseReadOptions(**parsed_options)
        else:
            options_obj = parsed_options

        return await storage_provider.list(location, options_obj)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid options JSON format")
    except Exception as e:
        logger.error(f"Storage list error: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{storage_type}/search")
async def search_storage_objects(
    storage_type: StorageType,
    path: str = Body(..., description="Storage path/identifier"),
    query: Union[str, Dict[str, Any], List[float]] = Body(..., description="Search query"),
    query_type: Optional[str] = Body("text", description="Query type (text, vector, metadata)"),
    limit: Optional[int] = Query(None, description="Result limit"),
    options: Optional[Dict[str, Any]] = Body(None, description="Storage-specific options")
):
    """Search across storage (DB query, file content search, IPFS search)"""

    if storage_type == StorageType.DATABASE:
        storage_provider = DatabaseStorageProvider()
    elif storage_type == StorageType.FILESYSTEM:
        storage_provider = FilesystemStorageProvider()
    elif storage_type == StorageType.IPFS:
        storage_provider = IPFSStorageProvider()
    else:
        raise HTTPException(400, "Invalid storage type")


    location = StorageLocation(storage_type, path)
    
    try:
        search_options = {
            "query_type": query_type,
            "limit": limit,
            **(options or {})
        }
        return await storage_provider.search(location, query, search_options)
    except Exception as e:
        raise HTTPException(500, str(e))

@router.put("/{storage_type}/update/{path:path}")
async def update_storage_object(
    storage_type: StorageType,
    path: str = Path(..., description="Storage path/identifier"),
    request_data: Optional[str] = Form(None, alias="data"),
    condition: Optional[str] = Query(None, description="Update condition (JSON string)")
):
    """Update storage objects (currently only supports database)"""
    request_data = json.loads(request_data) if request_data else None
    condition_dict = json.loads(condition) if condition else None

    logger.debug(f"Received update data: {request_data}")
    logger.debug(f"Received condition: {condition_dict}")

    location = StorageLocation(storage_type=storage_type, path=path)
    
    if storage_type == StorageType.DATABASE:
        storage_provider = DatabaseStorageProvider()
        if not request_data:
            raise HTTPException(400, "Database storage requires update data")
        options = {"condition": condition_dict} if condition_dict else None
        return await storage_provider.update(location, request_data, options)
    else:
        raise HTTPException(400, "Update currently only supports database storage")