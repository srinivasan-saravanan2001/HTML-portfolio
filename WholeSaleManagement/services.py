import urllib.parse
import csv
import io
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from .utils import get_wholesale_collection, serialize_item
from .pdf_generator import _build_invoice_pdf, build_ledger_pdf

async def process_ledger_data(
    company_name: str,
    start_date: Optional[str],
    end_date: Optional[str],
) -> Tuple[List[Dict], float, float, float]:
    collection = get_wholesale_collection()
    decoded_company_name = urllib.parse.unquote(company_name)
    parsed_start = datetime.fromisoformat(start_date) if start_date else None
    parsed_end = None
    if end_date:
        parsed_end = datetime.fromisoformat(end_date)
        parsed_end = parsed_end.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Filter includes both 'invoiced' and 'printed' as required
    filter_query = {
        "companyName": decoded_company_name,
        "companyStatus": {"$in": ["invoiced", "printed"]},
    }
    orders = await collection.find(filter_query).sort("createdDate", 1).to_list(length=1000)
    
    if not orders:
        return [], 0.0, 0.0, 0.0
    
    ledger_raw = []
    for order in orders:
        order_total = order.get("totalAmount", 0)
        order_date = order.get("createdDate")
        if isinstance(order_date, str):
            order_date = datetime.fromisoformat(order_date)

        # --- UPDATED LOGIC START ---
        # Determine the transaction type based on companyStatus
        status = order.get("companyStatus", "invoiced")
        
        if status == "printed":
            transaction_type = "Order"
            # Use orderId for printed orders as they might not have an invoiceNo yet
            reference_id = order.get("orderId", "N/A")
        else:
            # Default to "Invoice" for 'invoiced' or any other status
            transaction_type = "Invoice"
            # Prefer invoiceNo for invoiced orders, fallback to orderId
            reference_id = order.get("invoiceNo") or order.get("orderId", "N/A")

        ledger_raw.append({
            "date": order_date,
            "type": transaction_type, 
            "ref_id": reference_id,
            "description": f"{transaction_type} for {decoded_company_name}",
            "debit": order_total,
            "credit": 0,
        })
        # --- UPDATED LOGIC END ---

        payment_history = order.get("paymentHistory", [])
        if payment_history:
            for pmt in payment_history:
                pmt_amt = pmt.get("amount", 0)
                pmt_date = pmt.get("date")
                if isinstance(pmt_date, str):
                    pmt_date = datetime.fromisoformat(pmt_date)

                ledger_raw.append({
                    "date": pmt_date,
                    "type": "Payment",
                    "ref_id": pmt.get("mode", ""),
                    "description": "Payment Received",
                    "debit": 0,
                    "credit": pmt_amt,
                })
        else:
            paid = order.get("paidAmount", 0)
            if paid > 0:
                ledger_raw.append({
                    "date": order_date,
                    "type": "Payment",
                    "ref_id": order.get("orderId", ""),
                    "description": "Payment/Advance",
                    "debit": 0,
                    "credit": paid,
                })

    ledger_raw.sort(key=lambda x: x["date"] if x["date"] else datetime.min)
    running_balance = 0.0
    all_events_with_balance = []
    for event in ledger_raw:
        running_balance += event["debit"]
        running_balance -= event["credit"]
        all_events_with_balance.append({**event, "balance": running_balance})
    
    final_outstanding = running_balance
    
    ledger_entries = []
    for event in all_events_with_balance:
        event_date = event["date"]
        if event_date and (parsed_start or parsed_end):
            try:
                event_dt = (
                    event_date if isinstance(event_date, datetime)
                    else datetime.fromisoformat(str(event_date))
                )
                if parsed_start and event_dt < parsed_start:
                    continue
                if parsed_end and event_dt > parsed_end:
                    continue
            except Exception:
                pass
        ledger_entries.append(event)
    
    # Calculate totals for the summary (excluding filtered out dates)
    total_billed = sum(e["debit"] for e in ledger_entries if e["type"] in ["Invoice", "Order"])
    total_paid = sum(e["credit"] for e in ledger_entries if e["type"] == "Payment")
    
    return ledger_entries, total_billed, total_paid, final_outstanding
