from fastapi import FastAPI, HTTPException
from sqlmodel import SQLModel, Field, Session, create_engine, select
from enum import Enum
from typing import Optional, List
from datetime import date, datetime

# --- Models and enums ---
class TimeOffType(str, Enum):
    vacation = "vacation"
    sick = "sick"
    unpaid = "unpaid"

class Status(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class TimeOffRequestBase(SQLModel):
    employee: str
    approver: str
    type: TimeOffType
    start_date: date
    end_date: date
    reason: Optional[str] = None

class TimeOffRequest(TimeOffRequestBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status: Status = Field(default=Status.pending)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class TimeOffRequestCreate(TimeOffRequestBase):
    pass

class Decision(SQLModel):
    approver: str
    decision: Status

# --- DB ---
DATABASE_URL = "sqlite:///vacation.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def init_db():
    SQLModel.metadata.create_all(engine)

# --- App ---
app = FastAPI(title="Vacation Management")

@app.on_event("startup")
def on_startup():
    init_db()

# Create a request (employee)
@app.post("/requests/", response_model=TimeOffRequest)
def create_request(payload: TimeOffRequestCreate):
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    req = TimeOffRequest.from_orm(payload)
    with Session(engine) as session:
        session.add(req)
        session.commit()
        session.refresh(req)
        return req

# List requests for an approver (optionally filter by status)
@app.get("/requests/approver/{approver}", response_model=List[TimeOffRequest])
def list_requests_for_approver(approver: str, status: Optional[Status] = None):
    with Session(engine) as session:
        q = select(TimeOffRequest).where(TimeOffRequest.approver == approver)
        if status:
            q = q.where(TimeOffRequest.status == status)
        results = session.exec(q).all()
        return results

# Approver makes a decision
@app.post("/requests/{request_id}/decision", response_model=TimeOffRequest)
def decide_request(request_id: int, payload: Decision):
    with Session(engine) as session:
        req = session.get(TimeOffRequest, request_id)
        if not req:
            raise HTTPException(status_code=404, detail="Request not found")
        if req.approver != payload.approver:
            raise HTTPException(status_code=403, detail="Only the assigned approver can decide")
        if payload.decision not in (Status.approved, Status.rejected):
            raise HTTPException(status_code=400, detail="Decision must be 'approved' or 'rejected'")
        req.status = payload.decision
        session.add(req)
        session.commit()
        session.refresh(req)
        return req

# Get calendar of approved absences for a month
@app.get("/calendar")
def calendar(year: int, month: int):
    # returns list of approved requests that overlap the month
    from calendar import monthrange
    start_of_month = date(year, month, 1)
    last_day = monthrange(year, month)[1]
    end_of_month = date(year, month, last_day)

    with Session(engine) as session:
        q = select(TimeOffRequest).where(TimeOffRequest.status == Status.approved)
        results = session.exec(q).all()

    def overlaps(r: TimeOffRequest):
        return not (r.end_date < start_of_month or r.start_date > end_of_month)

    overlap_list = [r for r in results if overlaps(r)]
    # Simple summary: employee and dates
    summary = [
        {
            "id": r.id,
            "employee": r.employee,
            "type": r.type.value,
            "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat(),
        }
        for r in overlap_list
    ]
    return {"year": year, "month": month, "approved_absences": summary}

# Simple healthcheck
@app.get("/")
def root():
    return {"status": "ok"}
