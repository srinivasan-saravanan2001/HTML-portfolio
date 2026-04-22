from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from AdminLogin.routes import router as adminlogin_router
from CustomerRegistration.routes import router as customerregistration_router
from DynamicFeilds.routes import router as dynamicfeilds_router
from PhoneRegistration.routes import router as phoneregistration_router
from promotionalOffer.routes import router as promotionaloffer_router
from PromotionalOfferItems.routes import router as promotionalofferitems_router
from WholeSaleManagement.routes import router as wholesalemanegemnt_router
from CustomerTransaction.routes import router as customertransaction_router
from CustomerManagement.routes import router as customermanagement_router


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(adminlogin_router,prefix="/login",tags=["adminlogin"])
app.include_router(customerregistration_router,prefix="/register",tags=["register"])
app.include_router(dynamicfeilds_router,prefix="/dynamicfeilds",tags=["dynamicfeilds"])
app.include_router(phoneregistration_router,prefix="/crmapi",tags=["phoneRegistration"])
app.include_router(promotionaloffer_router,prefix="/promotionaloffers",tags=["promotionaloffers"])
app.include_router(promotionalofferitems_router,prefix="/promotionalofferitems",tags=["promotionalofferitems"]) 
app.include_router(wholesalemanegemnt_router,prefix="/wholesale",tags=["wholesale"])
app.include_router(customertransaction_router,prefix="/customertranaction",tags=["customertransaction"])
app.include_router(customermanagement_router,prefix="/customermanagement",tags=["customermanagement"])


@app.get("/")
def read_root():
    return {"message": "Welcome to the API"}

