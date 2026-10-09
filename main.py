from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from AdminLogin.routes import router as adminlogin_router
from WholeSaleManagement.routes import router as wholesalemanegemnt_router
from WholeSaleManagementVariance.routes import router as wholesalemanagementvarinace_router
from CustomerManagement.routes import router as customermanagement_router
from PaymentMaster.routes import router as paymentmaster_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(adminlogin_router,prefix="/login",tags=["adminlogin"])
app.include_router(wholesalemanegemnt_router,prefix="/wholesale",tags=["wholesale"])
app.include_router(wholesalemanagementvarinace_router,prefix="/wholesalevariance",tags=["wholesalevarinace"])
app.include_router(customermanagement_router,prefix="/customermanagement",tags=["customermanagement"])
app.include_router(paymentmaster_router,prefix="/paymentmaster",tags=["paymentmaster"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the API"}

