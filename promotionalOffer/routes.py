from datetime import datetime, timedelta
import re
import logging
import asyncio
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict, List, Optional
from bson import ObjectId
from pymongo import UpdateOne
from datetime import datetime, timedelta, timezone 
from promotionalOffer.models import PromotionalOffer, PromotionalOfferCreate, PromotionalOfferUpdate
from promotionalOffer.utils import get_promtionaloffer_collection, is_offer_expired, parse_date, parse_time
from PromotionalOfferItems.utils import (
    get_location_collection,
    get_category_collection,
    get_itemsubcategory_collection,
    get_orderType_collection,
    get_itemMaster_collection
)

logger = logging.getLogger(__name__)
router = APIRouter()
collection = get_promtionaloffer_collection()
IST = timezone(timedelta(hours=5, minutes=30))


def validate_and_convert_grams_to_kg(value):
    if value is None:
        return None, None  # ✅ Allow None to clear the field
    
    if isinstance(value, float):
        return round(value, 3), None
    
    if isinstance(value, int):
        # ✅ Removed the 1-2000 restriction as requested
        return round(value / 1000, 3), None
    
    elif isinstance(value, list):
        kg_list = []
        for v in value:
            if isinstance(v, float):
                kg_list.append(round(v, 3))
            elif isinstance(v, int):
                # ✅ Removed the 1-2000 restriction
                kg_list.append(round(v / 1000, 3))
            else:
                return None, "All grams values must be integers or floats"
        return kg_list, None
    
    return None, "Invalid format for grams"



async def _get_bulk_mapping(collection_conn, id_field: str, name_field: str, ids: List[str]) -> Dict[str, str]:
    """Helper to fetch ID->Name map in one query."""
    if not ids: return {}
    try:
        unique_ids = list(set(ids))
        cursor = collection_conn.find({id_field: {"$in": unique_ids}}, {id_field: 1, name_field: 1, "_id": 0})
        docs = await cursor.to_list(length=None)
        return {doc[id_field]: doc[name_field] for doc in docs}
    except Exception:
        return {}

async def resolve_names_for_offers(offers: List[Dict]) -> List[Dict]:
    if not offers: return []

    all_loc, all_cat, all_sub, all_order, all_item, all_var = set(), set(), set(), set(), set(), set()
    for o in offers:
        if o.get('locations'): all_loc.update(o['locations'])
        if o.get('category') or o.get('category1'): all_cat.update(o.get('category', []) + o.get('category1', []))
        if o.get('subcategory') or o.get('subcategory1'): all_sub.update(o.get('subcategory', []) + o.get('subcategory1', []))
        if o.get('appTypes'): all_order.update(o['appTypes'])
        if o.get('itemName') or o.get('itemName1'): all_item.update(o.get('itemName', []) + o.get('itemName1', []))
        if o.get('varianceName') or o.get('varianceName1'): all_var.update(o.get('varianceName', []) + o.get('varianceName1', []))

    loc_map, cat_map, sub_map, ord_map, item_map, var_map = await asyncio.gather(
        _get_bulk_mapping(get_location_collection(), "locationId", "branchName", list(all_loc)),
        _get_bulk_mapping(get_category_collection(), "categoryId", "categoryName", list(all_cat)),
        _get_bulk_mapping(get_itemsubcategory_collection(), "subCategoryId", "subCategoryName", list(all_sub)),
        _get_bulk_mapping(get_orderType_collection(), "orderTypeId", "orderTypeName", list(all_order)),
        _get_bulk_mapping(get_itemMaster_collection(), "itemCode", "itemName", list(all_item)),
        _get_bulk_mapping(get_itemMaster_collection(), "itemCode", "varianceName", list(all_var)),
    )

    for o in offers:
        if o.get('appTypes'): o['appTypes'] = [ord_map.get(x, x) for x in o['appTypes']]
        if o.get('locations'): o['locations'] = [loc_map.get(x, x) for x in o['locations']]
        if o.get('category'): o['category'] = [cat_map.get(x, x) for x in o['category']]
        if o.get('category1'): o['category1'] = [cat_map.get(x, x) for x in o['category1']]
        if o.get('subcategory'): o['subcategory'] = [sub_map.get(x, x) for x in o['subcategory']]
        if o.get('subcategory1'): o['subcategory1'] = [sub_map.get(x, x) for x in o['subcategory1']]
        if o.get('itemName'): o['itemName'] = [item_map.get(x, x) for x in o['itemName']]
        if o.get('itemName1'): o['itemName1'] = [item_map.get(x, x) for x in o['itemName1']]
        if o.get('varianceName'): o['varianceName'] = [var_map.get(x, x) for x in o['varianceName']]
        if o.get('varianceName1'): o['varianceName1'] = [var_map.get(x, x) for x in o['varianceName1']]
    return offers



async def auto_update_offer_status():
    try:
        required_fields = {
            'promotionalOfferId': 1, 'startDate': 1, 'endDate': 1,
            'weekdays': 1, 'fromTime': 1, 'toTime': 1
        }
        
        # 1. Deactivate expired
        active_offers = await collection.find({"status": "active"}, required_fields).to_list(length=None)
        
        # CHANGED: Use a for-loop to be safe and clear (is_offer_expired is synchronous now)
        deactivate_ops = []
        for o in active_offers:
            if is_offer_expired(o):
                deactivate_ops.append(UpdateOne(
                    {'promotionalOfferId': o['promotionalOfferId']}, {'$set': {'status': 'inactive'}}
                ))
        
        if deactivate_ops:
            res = await collection.bulk_write(deactivate_ops)
            logger.info(f"✅ Auto-deactivated {res.modified_count} offers")

        # 2. Activate valid
        inactive_offers = await collection.find({"status": "inactive"}, required_fields).to_list(length=None)
        
        activate_ops = []
        for o in inactive_offers:
            if not is_offer_expired(o):
                activate_ops.append(UpdateOne(
                    {'promotionalOfferId': o['promotionalOfferId']}, {'$set': {'status': 'active'}}
                ))
        
        if activate_ops:
            res = await collection.bulk_write(activate_ops)
            logger.info(f"✅ Auto-activated {res.modified_count} offers")
            
    except Exception as e:
        logger.error(f"Error in auto-update: {e}")



async def get_location_ids_from_names(location_names: List[str]) -> List[str]:
    if not location_names: return []
    try:
        cursor = get_location_collection().find({"branchName": {"$in": location_names}}, {"locationId": 1, "branchName": 1, "_id": 0})
        locs = await cursor.to_list(length=None)
        mp = {l["branchName"]: l["locationId"] for l in locs}
        return [mp.get(n, n) for n in location_names]
    except: return location_names

async def get_category_ids_from_names(category_names: List[str]) -> List[str]:
    if not category_names: return []
    try:
        cursor = get_category_collection().find({"categoryName": {"$in": category_names}}, {"categoryId": 1, "categoryName": 1, "_id": 0})
        cats = await cursor.to_list(length=None)
        mp = {c["categoryName"]: c["categoryId"] for c in cats}
        return [mp.get(n, n) for n in category_names]
    except: return category_names

async def get_subcategory_ids_from_names(subcategory_names: List[str]) -> List[str]:
    if not subcategory_names: return []
    try:
        cursor = get_itemsubcategory_collection().find({"subCategoryName": {"$in": subcategory_names}}, {"subCategoryId": 1, "subCategoryName": 1, "_id": 0})
        subcats = await cursor.to_list(length=None)
        mp = {s["subCategoryName"]: s["subCategoryId"] for s in subcats}
        return [mp.get(n, n) for n in subcategory_names]
    except: return subcategory_names

async def get_ordertype_ids_from_names(ordertype_names: List[str]) -> List[str]:
    if not ordertype_names: return []
    try:
        cursor = get_orderType_collection().find({"orderTypeName": {"$in": ordertype_names}}, {"orderTypeId": 1, "orderTypeName": 1, "_id": 0})
        types = await cursor.to_list(length=None)
        mp = {t["orderTypeName"]: t["orderTypeId"] for t in types}
        return [mp.get(n, n) for n in ordertype_names]
    except: return ordertype_names

async def get_item_codes_from_names(item_names: List[str]) -> List[str]:
    if not item_names: return []
    try:
        cursor = get_itemMaster_collection().find({"itemName": {"$in": item_names}}, {"itemCode": 1, "itemName": 1, "_id": 0})
        items = await cursor.to_list(length=None)
        mp = {i["itemName"]: i["itemCode"] for i in items}
        return [mp.get(n, n) for n in item_names]
    except: return item_names




async def get_variance_codes_from_names(variance_names: List[str]) -> List[str]:
    if not variance_names: return []
    try:
        cursor = get_itemMaster_collection().find({"varianceName": {"$in": variance_names}}, {"itemCode": 1, "varianceName": 1, "_id": 0})
        vars = await cursor.to_list(length=None)
        mp = {v["varianceName"]: v["itemCode"] for v in vars}
        return [mp.get(n, n) for n in variance_names]
    except: return variance_names










@router.post('/', response_model=PromotionalOffer)
async def create_promotional_offer(offer: PromotionalOfferCreate):
    offer_dict = offer.dict(exclude_unset=True)
    if offer_dict.get('appTypes'): offer_dict['appTypes'] = await get_ordertype_ids_from_names(offer_dict['appTypes'])
    if offer_dict.get('locations'): offer_dict['locations'] = await get_location_ids_from_names(offer_dict['locations'])
    if offer_dict.get('category'): offer_dict['category'] = await get_category_ids_from_names(offer_dict['category'])
    if offer_dict.get('subcategory'): offer_dict['subcategory'] = await get_subcategory_ids_from_names(offer_dict['subcategory'])
    if offer_dict.get('itemName'): offer_dict['itemName'] = await get_item_codes_from_names(offer_dict['itemName'])
    if offer_dict.get('varianceName'): offer_dict['varianceName'] = await get_variance_codes_from_names(offer_dict['varianceName'])
    if offer_dict.get('category1'): offer_dict['category1'] = await get_category_ids_from_names(offer_dict['category1'])
    if offer_dict.get('subcategory1'): offer_dict['subcategory1'] = await get_subcategory_ids_from_names(offer_dict['subcategory1'])
    if offer_dict.get('itemName1'): offer_dict['itemName1'] = await get_item_codes_from_names(offer_dict['itemName1'])
    if offer_dict.get('varianceName1'): offer_dict['varianceName1'] = await get_variance_codes_from_names(offer_dict['varianceName1'])

    for field_name in ["itemGrams", "varianceGrams", "freeItemGrams", "freeVarianceGrams"]:
        grams_dict = offer_dict.get(field_name)
        if grams_dict:
            converted_dict = {}
            for name, grams_value in grams_dict.items():
                kg_value, error = validate_and_convert_grams_to_kg(grams_value)
                if error: raise HTTPException(status_code=422, detail=f"Invalid grams for '{name}' in field '{field_name}': {error}")
                converted_dict[name] = kg_value
            offer_dict[field_name] = converted_dict

    offer_dict['promotionalOfferId'] = str(ObjectId())
    offer_dict['status'] = 'active'

    result = await collection.insert_one(offer_dict)
    if result.inserted_id:
        created_offer = await collection.find_one({'promotionalOfferId': offer_dict['promotionalOfferId']})
        return (await resolve_names_for_offers([created_offer]))[0]
    raise HTTPException(status_code=500, detail="Error creating promotional offer")




@router.patch('/{offer_id}', response_model=PromotionalOffer)
async def update_promotional_offer(offer_id: str, offer: PromotionalOfferUpdate):
    update_data = offer.dict(exclude_unset=True)
    if 'appTypes' in update_data: update_data['appTypes'] = await get_ordertype_ids_from_names(update_data['appTypes'])
    if 'locations' in update_data: update_data['locations'] = await get_location_ids_from_names(update_data['locations'])
    if 'category' in update_data: update_data['category'] = await get_category_ids_from_names(update_data['category'])
    if 'subcategory' in update_data: update_data['subcategory'] = await get_subcategory_ids_from_names(update_data['subcategory'])
    if 'itemName' in update_data: update_data['itemName'] = await get_item_codes_from_names(update_data['itemName'])
    if 'varianceName' in update_data: update_data['varianceName'] = await get_variance_codes_from_names(update_data['varianceName'])
    if 'category1' in update_data: update_data['category1'] = await get_category_ids_from_names(update_data['category1'])
    if 'subcategory1' in update_data: update_data['subcategory1'] = await get_subcategory_ids_from_names(update_data['subcategory1'])
    if 'itemName1' in update_data: update_data['itemName1'] = await get_item_codes_from_names(update_data['itemName1'])
    if 'varianceName1' in update_data: update_data['varianceName1'] = await get_variance_codes_from_names(update_data['varianceName1'])

    # ✅ Separate fields to $set vs $unset
    unset_fields = {}
    for field in ["itemGrams", "varianceGrams", "freeItemGrams", "freeVarianceGrams"]:
        if field in update_data:
            if update_data[field] is None:
                # null sent from frontend → remove the field from MongoDB
                unset_fields[field] = ""
                del update_data[field]
            else:
                converted_dict = {}
                for name, grams_value in update_data[field].items():
                    kg_value, error = validate_and_convert_grams_to_kg(grams_value)
                    if error:
                        raise HTTPException(status_code=422, detail=f"Invalid grams for '{name}' in '{field}': {error}")
                    converted_dict[name] = kg_value
                update_data[field] = converted_dict
    mongo_update = {}
    if update_data:
        mongo_update["$set"] = update_data
    if unset_fields:
        mongo_update["$unset"] = unset_fields

    if not mongo_update:
        raise HTTPException(status_code=400, detail="No update data provided")

    result = await collection.update_one({'promotionalOfferId': offer_id}, mongo_update)
    if result.modified_count == 1 or result.matched_count == 1:
        updated_offer = await collection.find_one({'promotionalOfferId': offer_id})
        if updated_offer: return (await resolve_names_for_offers([updated_offer]))[0]
    raise HTTPException(status_code=404, detail="Promotional offer not found")



@router.get('/', response_model=Dict[str, Any])
async def get_promotional_offers(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    await auto_update_offer_status()
    pipeline = []
    match_stage = {}
    if status: match_stage["status"] = status
    if search and search.strip():
        regex = re.escape(search.strip())
        match_stage["$or"] = [
            {"coupencode": {"$regex": regex, "$options": "i"}},
            {"offerName": {"$regex": regex, "$options": "i"}}
        ]
    
    if match_stage:
        pipeline.append({"$match": match_stage})

    pipeline.append({
        "$facet": {
            "data": [
                {"$skip": (page - 1) * limit},
                {"$limit": limit},
                {
                    "$lookup": {
                        "from": "Location",
                        "let": {"locIds": "$locations"},
                        "pipeline": [
                            {"$match": {"$expr": {"$in": ["$locationId", "$$locIds"]}}},
                            {"$project": {"locationId": 1, "branchName": 1, "_id": 0}}
                        ],
                        "as": "location_docs"
                    }
                },
                {
                    "$lookup": {
                        "from": "ItemCategory",
                        "let": {"catIds": {"$concatArrays": ["$category", "$category1"]}},
                        "pipeline": [
                            {"$match": {"$expr": {"$in": ["$categoryId", "$$catIds"]}}},
                            {"$project": {"categoryId": 1, "categoryName": 1, "_id": 0}}
                        ],
                        "as": "category_docs"
                    }
                },
                {
                    "$lookup": {
                        "from": "ItemSubCategory",
                        "let": {"subIds": {"$concatArrays": ["$subcategory", "$subcategory1"]}},
                        "pipeline": [
                            {"$match": {"$expr": {"$in": ["$subCategoryId", "$$subIds"]}}},
                            {"$project": {"subCategoryId": 1, "subCategoryName": 1, "_id": 0}}
                        ],
                        "as": "subcategory_docs"
                    }
                },
                {
                    "$lookup": {
                        "from": "OrderType",
                        "let": {"orderIds": "$appTypes"},
                        "pipeline": [
                            {"$match": {"$expr": {"$in": ["$orderTypeId", "$$orderIds"]}}},
                            {"$project": {"orderTypeId": 1, "orderTypeName": 1, "_id": 0}}
                        ],
                        "as": "order_docs"
                    }
                },
                {
                    "$lookup": {
                        "from": "ItemMaster",
                        "let": {"itemCodes": {"$concatArrays": ["$itemName", "$itemName1", "$varianceName", "$varianceName1"]}},
                        "pipeline": [
                            {"$match": {"$expr": {"$in": ["$itemCode", "$$itemCodes"]}}},
                            {"$project": {"itemCode": 1, "itemName": 1, "varianceName": 1, "_id": 0}}
                        ],
                        "as": "item_docs"
                    }
                },
                # Stage 4: Project (Format the output to match PromotionalOffer Model)
                {
                    "$project": {
                        "_id": 0,
                        "promotionalOfferId": 1,
                        "offerName": 1,
                        "startDate": 1,
                        "endDate": 1,
                        "weekdays": 1,
                        "fromTime": 1,
                        "toTime": 1,
                        "status": 1,
                        "appTypes": {
                            "$map": {
                                "input": "$appTypes",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$order_docs.orderTypeName", {"$indexOfArray": ["$order_docs.orderTypeId", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "locations": {
                            "$map": {
                                "input": "$locations",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$location_docs.branchName", {"$indexOfArray": ["$location_docs.locationId", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "category": {
                            "$map": {
                                "input": "$category",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$category_docs.categoryName", {"$indexOfArray": ["$category_docs.categoryId", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "category1": {
                            "$map": {
                                "input": "$category1",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$category_docs.categoryName", {"$indexOfArray": ["$category_docs.categoryId", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "subcategory": {
                            "$map": {
                                "input": "$subcategory",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$subcategory_docs.subCategoryName", {"$indexOfArray": ["$subcategory_docs.subCategoryId", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "subcategory1": {
                            "$map": {
                                "input": "$subcategory1",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$subcategory_docs.subCategoryName", {"$indexOfArray": ["$subcategory_docs.subCategoryId", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "itemName": {
                            "$map": {
                                "input": "$itemName",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$item_docs.itemName", {"$indexOfArray": ["$item_docs.itemCode", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "itemName1": {
                            "$map": {
                                "input": "$itemName1",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$item_docs.itemName", {"$indexOfArray": ["$item_docs.itemCode", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "varianceName": {
                            "$map": {
                                "input": "$varianceName",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$item_docs.varianceName", {"$indexOfArray": ["$item_docs.itemCode", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "varianceName1": {
                            "$map": {
                                "input": "$varianceName1",
                                "as": "id",
                                "in": {
                                    "$ifNull": [
                                        {"$arrayElemAt": ["$item_docs.varianceName", {"$indexOfArray": ["$item_docs.itemCode", "$$id"]}]},
                                        "$$id"
                                    ]
                                }
                            }
                        },
                        "configuration": 1,
                        "discountPercentage": 1,
                        "discountValue": 1,
                        "orderValue": 1,
                        "orderDiscountValue": 1,
                        "orderDiscountPercentage": 1,
                        "coupencode": 1,
                        "coupenmode": 1,
                        "buy": 1,
                        "get": 1,
                        "offerType": 1,
                        "freeoffer": 1,
                        "discountOffer": 1,
                        "itemGrams": 1,
                        "varianceGrams": 1,
                        "freeItemGrams": 1,
                        "freeVarianceGrams": 1,
                        "customers": 1,
                        "image": 1,
                        "selectionType": 1,
                        "selectionType1": 1,
                        "selectionType2": 1
                    }
                }
            ],
            "totalCount": [
                {"$count": "count"}
            ]
        }
    })

    # Execute Pipeline
    result = await collection.aggregate(pipeline).to_list(length=1)
    
    if not result or not result[0]:
        return {
            "data": [],
            "page": page,
            "limit": limit,
            "total": 0,
            "total_pages": 0,
            "has_more": False,
            "search": search
        }
    
    facet_data = result[0]
    offers = facet_data.get("data", [])
    total_count = facet_data.get("totalCount", [{}])[0].get("count", 0)
    
    total_pages = (total_count + limit - 1) // limit if limit > 0 else 0
    has_more = page < total_pages

    return {
        "data": offers,
        "page": page,
        "limit": limit,
        "total": total_count,
        "total_pages": total_pages,
        "has_more": has_more,
        "search": search
    }




@router.get('/{offer_id}', response_model=PromotionalOffer)
async def get_promotional_offer(offer_id: str):
    offer = await collection.find_one({'promotionalOfferId': offer_id})
    if offer: return (await resolve_names_for_offers([offer]))[0]
    raise HTTPException(status_code=404, detail="Promotional offer not found")





@router.patch('/deactivate/{offer_id}', response_model=PromotionalOffer)
async def deactivate_promotional_offer(offer_id: str):
    result = await collection.update_one({'promotionalOfferId': offer_id}, {'$set': {'status': 'inactive'}})
    if result.modified_count == 1 or result.matched_count == 1:
        updated_offer = await collection.find_one({'promotionalOfferId': offer_id})
        if updated_offer: return (await resolve_names_for_offers([updated_offer]))[0]
    raise HTTPException(status_code=404, detail="Promotional offer not found")





@router.patch('/activate/{offer_id}', response_model=PromotionalOffer)
async def activate_promotional_offer(
    offer_id: str, 
    offerData: Optional[PromotionalOfferUpdate] = None,
    skip_time_check: bool = Query(False)
):
    offer = await collection.find_one({'promotionalOfferId': offer_id})
    if not offer: raise HTTPException(status_code=404, detail="Promotional offer not found")

    if offerData:
        update_dict = offerData.dict(exclude_unset=True, exclude_none=True)
        if 'appTypes' in update_dict: update_dict['appTypes'] = await get_ordertype_ids_from_names(update_dict['appTypes'])
        if 'locations' in update_dict: update_dict['locations'] = await get_location_ids_from_names(update_dict['locations'])
        await collection.update_one({'promotionalOfferId': offer_id}, {'$set': update_dict})
        offer = await collection.find_one({'promotionalOfferId': offer_id})

    errors = []
    start_date_str, end_date_str = offer.get('startDate'), offer.get('endDate')
    if start_date_str and end_date_str:
        sd, ed = parse_date(start_date_str), parse_date(end_date_str)
        if sd and ed and sd > ed: errors.append(f"Start date ({sd}) cannot be after End date ({ed})")

    allowed_days = offer.get('weekdays', [])
    if not allowed_days: errors.append("At least one active weekday must be selected")

    from_time_str, to_time_str = offer.get('fromTime'), offer.get('toTime')
    if from_time_str and to_time_str:
        ft, tt = parse_time(from_time_str), parse_time(to_time_str)
        if ft and tt and ft == tt: errors.append("Start time and End time cannot be the same")

    if errors: raise HTTPException(status_code=400, detail="Invalid offer data: " + "; ".join(errors))

    if not skip_time_check:
        # CHANGED: Calculate IST time explicitly
        # 1. Get UTC time
        now_utc = datetime.now(timezone.utc)
        # 2. Convert to IST
        now = now_utc.astimezone(IST).replace(tzinfo=None)
        
        curr_date, curr_time, curr_wd = now.date(), now.time(), now.strftime('%A')
        
        if end_date_str:
            ed = parse_date(end_date_str)
            if ed and curr_date > ed: errors.append(f"End date {ed} has passed (IST)")
        if start_date_str:
            sd = parse_date(start_date_str)
            if sd and curr_date < sd: errors.append(f"Start date {sd} is in the future (IST)")
        if allowed_days and curr_wd not in allowed_days: 
            errors.append(f"Today ({curr_wd} IST) is not an allowed day")
        if from_time_str and to_time_str:
            ft, tt = parse_time(from_time_str), parse_time(to_time_str)
            if ft and tt:
                if ft < tt:
                    if not (ft <= curr_time <= tt): errors.append(f"Current time (IST) outside window")
                else:
                    if not (curr_time >= ft or curr_time <= tt): errors.append(f"Current time (IST) outside overnight window")
        if errors: raise HTTPException(status_code=400, detail="Cannot activate right now: " + "; ".join(errors))

    result = await collection.update_one({'promotionalOfferId': offer_id}, {'$set': {'status': 'active'}})
    if result.modified_count == 1 or result.matched_count == 1:
        final_offer = await collection.find_one({'promotionalOfferId': offer_id})
        if final_offer:
            logger.info(f"✅ Offer activated: {offer_id}")
            return (await resolve_names_for_offers([final_offer]))[0]
    raise HTTPException(status_code=500, detail="Failed to activate offer")



