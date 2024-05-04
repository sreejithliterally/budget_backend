from enum import Enum
from typing import List, Optional, Union, Dict
from fastapi import FastAPI, HTTPException, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from config import settings
from datetime import datetime, date
import json

# Define SQLAlchemy models
Base = declarative_base()




class Expensecategory(Base):
    __tablename__ = "expense_category"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    # Define a relationship with the User model
    user = relationship("User", back_populates="categories")

# Define User class after ExpenseCategory class
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    expenses = relationship("Expense", back_populates="user")
    budget_allocations = relationship("BudgetAllocationTable", back_populates="user")  # New relationship
    categories = relationship("Expensecategory", back_populates="user")  # Relationship with ExpenseCategory model

# Configure the relationship between User and ExpenseCategory models
Expensecategory.user = relationship("User", back_populates="categories")

class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float)
    category = Column(String)
    date = Column(Date)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="expenses")


class BudgetAllocationTable(Base):
    __tablename__ = "budget_allocation"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))  # Foreign key relationship with the users table
    user = relationship("User", back_populates="budget_allocations")  # Relationship with the User model
    groceries = Column(Float, default=0.0)
    fuel = Column(Float, default=0.0)
    bills = Column(Float, default=0.0)
    travel = Column(Float, default=0.0)
    apparel = Column(Float, default=0.0)
    utilities = Column(Float, default=0.0)
    other = Column(Float, default=0.0)



   
class ExpenseCategory(str, Enum):
    groceries = "groceries"
    fuel = "fuel"
    bills = "bills"
    travel = "travel"
    apparel = "apparel"
    utilities = "utilities"
    other = "other"

class ExpenseCreate(BaseModel):
    groceries: float
    fuel: float
    bills: float
    travel: float
    apparel: float
    utilities: float
    other: float
    date: date

class ExpenseResponse(BaseModel):
    id: int
    amount: float
    category: str
    date: date
    user_id: int

# Pydantic model for request validation
class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

# Define Pydantic model for response
class UserResponse(BaseModel):
    id: int
    username: str

class BudgetAllocation(BaseModel):
    Groceries: Optional[float]
    Fuel: Optional[float]
    Bills: Optional[float]
    Travel: Optional[float]
    Apparel: Optional[float]
    Utilities: Optional[float]
    Other: Optional[float]

# Initialize FastAPI app
app = FastAPI()

# Database setup
SQLALCHEMY_DATABASE_URL = f'postgresql://{settings.database_username}:{settings.database_password}@{settings.database_hostname}:{settings.database_port}/{settings.database_name}'
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# User registration endpoint
@app.post("/register/", response_model=UserResponse)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = User(username=user.username, password=user.password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# User login endpoint
@app.post("/login/")
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or db_user.password != user.password:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return {"message": "Login successful"}

class BudgetAllocationResponse(BaseModel):
    groceries: float
    fuel: float
    bills: float
    travel: float
    apparel: float
    utilities: float
    other: float



class ExpenseCategoryResponse(BaseModel):
    id: int
    name: str
    user_id: int


@app.post("/budgets/", response_model=BudgetAllocationResponse)
def allocate_budget(budget: BudgetAllocation, user_id: int, db: Session = Depends(get_db)):
    # Check if any category has a negative value
    if any(value and value < 0 for value in budget.dict().values()):
        raise HTTPException(status_code=400, detail="Budget values cannot be negative")

    # Convert keys to lowercase
    budget_dict_lower = {key.lower(): value for key, value in budget.dict().items()}

    # Retrieve or create the budget allocation record for the user
    budget_allocation = db.query(BudgetAllocationTable).filter(BudgetAllocationTable.user_id == user_id).first()
    if not budget_allocation:
        budget_allocation = BudgetAllocationTable(**budget_dict_lower, user_id=user_id)  # Associate with user
        db.add(budget_allocation)
    else:
        for category, value in budget_dict_lower.items():
            setattr(budget_allocation, category, value)

    db.commit()
    db.refresh(budget_allocation)

    # Convert the SQLAlchemy model instance to a dictionary
    budget_allocation_dict = jsonable_encoder(budget_allocation)

    # Return the budget allocation as a JSON response
    return budget_allocation_dict

# Create expense endpoint
@app.post("/expenses/", response_model=ExpenseResponse)
def create_expense(expense: ExpenseCreate, user_id: int, db: Session = Depends(get_db)):
    # Create the expense
    db_expense = Expense(amount=sum([getattr(expense, category_name) for category_name in ExpenseCategory]),
                         category=json.dumps({category_name: getattr(expense, category_name) for category_name in ExpenseCategory}),
                         date=expense.date, user_id=user_id)
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)

    # Deduct the expense amount from the budget allocation
    budget_allocation = db.query(BudgetAllocationTable).first()
    if not budget_allocation:
        raise HTTPException(status_code=404, detail="Budget allocation not found")

    # Update the budget allocation based on the expense categories
    for category_name in ExpenseCategory:
        expense_amount = getattr(expense, category_name)
        if expense_amount > 0:
            setattr(budget_allocation, category_name, getattr(budget_allocation, category_name) - expense_amount)

    db.commit()

    return db_expense

# Calculate monthly expenses endpoint
@app.get("/expenses/monthly/{user_id}/{month}/{year}")
def calculate_monthly_expenses(user_id: int, month: int, year: int, db: Session = Depends(get_db)) -> Dict[str, Dict[str, float]]:
    start_date = date(year, month, 1)
    end_date = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)

    total_expense = db.query(func.sum(Expense.amount)).filter(Expense.date >= start_date, Expense.date < end_date, Expense.user_id == user_id).scalar() or 0.0

    # Calculate expenses for each category
    category_expenses = db.query(Expense.category, func.sum(Expense.amount)).filter(Expense.date >= start_date, Expense.date < end_date, Expense.user_id == user_id).group_by(Expense.category).all()
    category_expenses_dict = {category: float(amount) for category, amount in category_expenses}
    response_dict = {"total": {"total_expense": total_expense}, "categories": category_expenses_dict}

    return response_dict
# Endpoint to get the status of the allocated budget
class BudgetStatusResponse(BaseModel):
    total_allocated: Dict[str, float]
    remaining_budget: Dict[str, float]


@app.get("/budgets/status/{user_id}", response_model=BudgetStatusResponse)
def get_budget_status(user_id: int, db: Session = Depends(get_db)):
    # Get the budget allocation for the user
    budget_allocation = db.query(BudgetAllocationTable).filter(BudgetAllocationTable.user_id == user_id).first()
    if not budget_allocation:
        raise HTTPException(status_code=404, detail="Budget allocation not found")

    # Calculate total allocated budget
    total_allocated = budget_allocation.__dict__
    total_allocated.pop('_sa_instance_state')  # Remove SQLAlchemy internal state

    # Calculate total expenses for each category
    total_expenses = db.query(Expense.category, func.sum(Expense.amount)).filter(Expense.user_id == user_id).group_by(Expense.category).all()
    total_expenses_dict = {category: float(amount) for category, amount in total_expenses}

    # Calculate remaining budget for each category
    remaining_budget = {category: total_allocated.get(category, 0.0) - total_expenses_dict.get(category, 0.0) for category in ExpenseCategory}

    return {"total_allocated": total_allocated, "remaining_budget": remaining_budget}



@app.post("/expenses/categories/{user_id}/add", response_model=None)
def add_category(user_id: int, category_name: str, db: Session = Depends(get_db)):
    # Check if the category already exists for the user
    existing_category = db.query(Expensecategory).filter(Expensecategory.user_id == user_id, Expensecategory.name == category_name).first()

    if existing_category:
        return {"message": "Category already exists"}

    # Create a new category for the user
    new_category = Expensecategory(user_id=user_id, name=category_name)
    db.add(new_category)
    db.commit()

    return {"message": "Category added successfully"}


class ExpenseCategory(BaseModel):
    id: int
    name: str
    user_id: int

class ExpenseCategoryResponse(BaseModel):
    id: int
    name: str
    user_id: int

@app.get("/expenses/categories/{user_id}", response_model=List[ExpenseCategoryResponse])
def get_user_categories(user_id: int, db: Session = Depends(get_db)) -> List[ExpenseCategoryResponse]:
    try:
        # Get predefined categories
        predefined_categories = db.query(Expensecategory).filter(Expensecategory.user_id.is_(None)).all()
        
        # Get user-specific categories
        user_categories = db.query(Expensecategory).filter_by(user_id=user_id).all()

        # Combine both lists
        all_categories = predefined_categories + user_categories

        # Convert to ExpenseCategoryResponse objects
        response_categories = []
        for category in all_categories:
            response_category = ExpenseCategoryResponse(id=category.id, name=category.name, user_id=category.user_id)
            response_categories.append(response_category)

        return response_categories
    except Exception as e:
        # Handle any errors and raise HTTP 500
        raise HTTPException(status_code=500, detail=f"Error fetching categories: {e}")