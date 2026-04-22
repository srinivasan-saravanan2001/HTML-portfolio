from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

TEST_URI = "mongodb://admin:YenE580nOOUE6cDhQERP@194.233.78.90:27017/admin?authSource=admin&authMechanism=SCRAM-SHA-256&replicaSet=yenerp-cluster"

client_test = AsyncIOMotorClient(TEST_URI)
db_flutter = client_test["YENERP_LIVE_DB"]

# ✅ ONLY THESE TWO COLLECTIONS
invoices = db_flutter["invoices"]
customers = db_flutter["customer"]


# ---------------- INDEXES ----------------
async def ensure_customer_indexes():
    try:
        await customers.create_index(
            [("customerPhoneNumber", 1)],
            name="idx_customer_phone",
            background=True
        )
        await customers.create_index(
            [("customerName", 1)],
            name="idx_customer_name",
            background=True
        )
        print("Customer indexes created successfully")
    except Exception as e:
        print(f"Error creating customer indexes: {e}")


async def ensure_invoice_indexes():
    try:
        await invoices.create_index(
            [("invoiceDateTime", -1)],
            name="idx_invoice_date",
            background=True
        )
        await invoices.create_index(
            [("totalAmount", -1)],
            name="idx_total_amount",
            background=True
        )
        await invoices.create_index(
            [("branchName", 1), ("invoiceDateTime", -1)],
            name="idx_branch_date",
            background=True
        )
        await invoices.create_index(
            [("salesPersonName", 1), ("invoiceDateTime", -1)],
            name="idx_salesperson_date",
            background=True
        )
        await invoices.create_index(
            [("customerPhoneNumber", 1)],
            name="idx_invoice_phone",
            background=True
        )
        print("Invoice indexes created successfully")
    except Exception as e:
        print(f"Error creating invoice indexes: {e}")


# ---------------- GETTERS ----------------
def get_invoices_collection():
    return invoices


def get_customers_collection():
    return customers