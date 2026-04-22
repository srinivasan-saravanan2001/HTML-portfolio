from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
import re
from .utils import get_itemsubcategory_collection, get_category_collection, get_itemMaster_collection, get_orderType_collection, get_location_collection, get_uom_collection

router = APIRouter()
async def get_uom_name_from_id(uom_id: str) -> str:
    if not uom_id or not str(uom_id).strip():
        return ""
    
    try:
        uom_collection = get_uom_collection()
        # Find the UOM document with this ID
        uom = await uom_collection.find_one(
            {"uomId": str(uom_id).strip()},
            {"uom": 1, "_id": 0}
        )
        
        if uom and uom.get("uom"):
            return uom["uom"]
        return ""
    except Exception as e:
        print(f"Error fetching UOM name for ID {uom_id}: {e}")
        return ""


def create_search_regex(search_term: str) -> dict:
    if not search_term:
        return {}
    escaped_term = re.escape(search_term)
    return {
        "$regex": f".*{escaped_term}.*", 
        "$options": "i" 
    }


def create_advanced_search_regex(search_term: str) -> dict:
 
    if not search_term:
        return {}
    
    escaped_term = re.escape(search_term)
    pattern = f"(^{escaped_term}$)|(^{escaped_term})|({escaped_term})"
    
    return {
        "$regex": pattern,
        "$options": "i"
    }


@router.get("/itemsprice", response_model=List[Dict[str, Any]])
async def get_simple_items(
    search: Optional[str] = Query(None, description="Search term for item names"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
):
    """Get Active items with their default prices, item codes, and UOM names (paginated)"""
    try:
        branchwise_items_collection = get_itemMaster_collection()
        
        # Base query for active items
        query = {
            "itemName": {"$exists": True, "$ne": None, "$ne": ""},
            "status": "Active",
            "notForSale": {"$ne": True}
        }
        
        # Add search condition if provided
        if search and search.strip():
            search_regex = create_search_regex(search.strip())
            if search_regex:
                query["itemName"] = search_regex
        
        skip = (page - 1) * limit
        
        # Get total count for pagination info
        total_count = await branchwise_items_collection.count_documents(query)
        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": "$itemName",
                "item_Defaultprice": {"$first": "$item_Defaultprice"},
                "itemCode": {"$first": "$itemCode"},
             
            }},
            {"$sort": {"_id": 1}},
            {"$skip": skip},
            {"$limit": limit},
            {"$project": {
                "itemName": "$_id",
                "item_Defaultprice": 1,
                "itemCode": 1,
                "_id": 0
            }}
        ]
        
        cursor = branchwise_items_collection.aggregate(pipeline)
        items = await cursor.to_list(length=None)
        
        # Build final response by fetching UOM name for each item
        result = []
        for item in items:
            
            result.append({
                "itemName": item["itemName"],
                "item_Defaultprice": item.get("item_Defaultprice", 0),
                "itemCode": item.get("itemCode", ""),
            })
        
        # You might want to return pagination info as well
        return result
        
    except Exception as e:  
        print(f"Error in itemsprice: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/variancesprice", response_model=Dict[str, Any])
async def get_simple_variances(
    search: Optional[str] = Query(None, description="Search term for variance names"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    max_price: Optional[float] = Query(None, description="Maximum price filter")
):
    """Get active variance names with default prices >= 5, item codes, and UOM names (paginated)"""
    try:
        branchwise_items_collection = get_itemMaster_collection()
        
        # Build query
        query = {
            "varianceName": {"$exists": True, "$ne": None, "$ne": ""},
            "status": {"$regex": "^active$", "$options": "i"},
            "variance_Defaultprice": {"$gte": 5}
        }
        
        # Add search if provided
        if search and search.strip():
            search_regex = create_search_regex(search.strip())
            if search_regex:
                query["varianceName"] = search_regex
        
        # Add price filter if provided
        if max_price is not None:
            try:
                max_price_value = float(max_price)
                if max_price_value > 0:
                    query["variance_Defaultprice"]["$lte"] = max_price_value
            except (ValueError, TypeError):
                pass
        
        # Get total count for pagination
        total_count = await branchwise_items_collection.count_documents(query)
        total_pages = (total_count + limit - 1) // limit
        has_more = page < total_pages
        
        skip = (page - 1) * limit
        
        # Get variances
        cursor = branchwise_items_collection.find(
            query,
            {
                "varianceName": 1,
                "variance_Defaultprice": 1,
                "itemCode": 1,
                "variance_Uom": 1,  # Use the correct field name
                "_id": 0
            }
        ).sort("varianceName", 1).skip(skip).limit(limit)  # Sort by name for better UX
        
        items = await cursor.to_list(length=None)
        
        # Build response
        validated_items = []
        for item in items:
            if item.get("variance_Defaultprice") and float(item["variance_Defaultprice"]) >= 5:
                uom_id = item.get('variance_Uom')
                uom_name = await get_uom_name_from_id(uom_id) if uom_id else ""
                
                validated_items.append({
                    "varianceName": item["varianceName"],
                    "variance_Defaultprice": item.get("variance_Defaultprice", 0),
                    "itemCode": item.get("itemCode", ""),
                    "variance_UOM": uom_name,
                })
        
        return {
            "data": validated_items,
            "page": page,
            "limit": limit,
            "total": total_count,
            "total_pages": total_pages,
            "has_more": has_more
        }
        
    except Exception as e:
        print(f"Error in variancesprice: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/categories", response_model=List[Dict[str, Any]])
async def get_active_categories(
    search: Optional[str] = Query(None, description="Search term for category names"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
):
    """Get active categories with categoryName and categoryId (paginated)"""
    try:
        category_collection = get_category_collection()
        
        # Base query for active categories
        query = {"status": "active"}
        
        # Add search if provided
        if search and search.strip():
            search_regex = create_search_regex(search.strip())
            if search_regex:
                query["categoryName"] = search_regex
        
        # Get total count
        total_count = await category_collection.count_documents(query)
        
        skip = (page - 1) * limit
        
        # Get categories
        cursor = category_collection.find(
            query,
            {
                "categoryName": 1,
                "categoryId": 1,
                "_id": 0
            }
        ).sort("categoryName", 1).skip(skip).limit(limit)
        
        categories = await cursor.to_list(length=None)
        
        return categories
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/subcategories", response_model=List[Dict[str, Any]])
async def get_active_subcategories(
    search: Optional[str] = Query(None, description="Search term for subcategory names"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
):
    """Get active subcategories with pagination"""
    try:
        itemsubcategory_collection = get_itemsubcategory_collection()
        
        # Base query for active subcategories
        query = {"status": "active"}
        
        # Add search if provided
        if search and search.strip():
            search_regex = create_search_regex(search.strip())
            if search_regex:
                query["subCategoryName"] = search_regex
        
        # Get total count
        total_count = await itemsubcategory_collection.count_documents(query)
        
        skip = (page - 1) * limit
        
        # Get subcategories
        cursor = itemsubcategory_collection.find(
            query,
            {
                "subCategoryName": 1,
                "subCategoryId": 1,
                "status": 1,
                "_id": 0
            }
        ).sort("subCategoryName", 1).skip(skip).limit(limit)
        
        subcategories = await cursor.to_list(length=None)
        
        return subcategories
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/ordertypes", response_model=List[Dict[str, Any]])
async def get_active_order_types(
    search: Optional[str] = Query(None, description="Search term for order type names")
):
    """Get all active order types with optional search"""
    try:
        orderType_collection = get_orderType_collection()
        
        # Base query for active order types
        query = {"status": "active"}
        
        # Add search if provided
        if search and search.strip():
            search_regex = create_search_regex(search.strip())
            if search_regex:
                query["orderTypeName"] = search_regex
        
        # Get order types
        cursor = orderType_collection.find(
            query,
            {
                "orderTypeName": 1,
                "orderTypeId": 1,
                "status": 1,
                "_id": 0
            }
        ).sort("orderTypeName", 1)
        
        order_types = await cursor.to_list(length=None)
        
        return order_types
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}") 


@router.get("/locations", response_model=List[Dict[str, Any]])
async def get_active_locations(
    search: Optional[str] = Query(None, description="Search term for location/branch names")
):
    """Get all active locations with branchName and locationId, with optional search"""
    try:
        location_collection = get_location_collection()
        
        # Base query for active locations
        query = {"status": "active"}
        
        # Add search if provided
        if search and search.strip():
            search_regex = create_search_regex(search.strip())
            if search_regex:
                query["branchName"] = search_regex
        
        # Get locations
        cursor = location_collection.find(
            query,
            {
                "branchName": 1,
                "locationId": 1,
                "status": 1,
                "_id": 0
            }
        ).sort("branchName", 1)
        
        locations = await cursor.to_list(length=None)
        
        return locations
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")