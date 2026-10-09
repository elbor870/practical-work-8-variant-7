from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    Session,
    sessionmaker,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("school_api")


DATABASE_URL = "sqlite:///./school.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


# =====================================================================
# МОДЕЛИ БАЗЫ ДАННЫХ
# =====================================================================


class Group(Base):
    """
    В школе группа — это класс, например 7А.
    """

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    grade_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    students: Mapped[List["Student"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fio: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    subjects: Mapped[List["Subject"]] = relationship(back_populates="teacher")


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    teacher_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
    )

    teacher: Mapped[Optional["Teacher"]] = relationship(back_populates="subjects")
    behavior_records: Mapped[List["BehaviorRecord"]] = relationship(
        back_populates="subject"
    )


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fio: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    enrollment_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        default=date.today,
    )

    # Оценка за поведение: 2, 3, 4, 5.
    # Может быть не выставлена, поэтому Optional.
    behavior_grade: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    group: Mapped[Optional["Group"]] = relationship(back_populates="students")
    behavior_records: Mapped[List["BehaviorRecord"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )


class BehaviorRecord(Base):
    """
    Вариант 7: журнал поведения.

    Хранит:
    - баллы за поведение;
    - замечания;
    - признак пропуска без уважительной причины.
    """

    __tablename__ = "behavior_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"),
        nullable=True,
    )

    record_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        default=date.today,
    )

    points: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )

    remark: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    is_unexcused_absence: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    student: Mapped["Student"] = relationship(back_populates="behavior_records")
    subject: Mapped[Optional["Subject"]] = relationship(
        back_populates="behavior_records"
    )


# =====================================================================
# PYDANTIC-СХЕМЫ
# =====================================================================


# ---------- Groups ----------


class GroupBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    grade_level: Optional[int] = Field(None, ge=1, le=11)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Название класса/группы не может быть пустым")
        return v


class GroupCreate(GroupBase):
    pass


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    grade_level: Optional[int] = Field(None, ge=1, le=11)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = " ".join(v.split())
        if not v:
            raise ValueError("Название класса/группы не может быть пустым")
        return v


class GroupOut(GroupBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ---------- Teachers ----------


class TeacherBase(BaseModel):
    fio: str = Field(..., min_length=5, max_length=200)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)

    @field_validator("fio")
    @classmethod
    def validate_fio(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 5:
            raise ValueError("ФИО слишком короткое")
        if len(v.split()) < 2:
            raise ValueError("ФИО должно содержать как минимум имя и фамилию")
        return v

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) < 10:
            raise ValueError("Телефон должен содержать не менее 10 цифр")
        return v


class TeacherCreate(TeacherBase):
    pass


class TeacherUpdate(BaseModel):
    fio: Optional[str] = Field(None, min_length=5, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)

    @field_validator("fio")
    @classmethod
    def validate_fio(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = " ".join(v.split())
        if len(v) < 5:
            raise ValueError("ФИО слишком короткое")
        if len(v.split()) < 2:
            raise ValueError("ФИО должно содержать как минимум имя и фамилию")
        return v

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: Optional[EmailStr]) -> Optional[str]:
        if v is None:
            return None
        return str(v).lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) < 10:
            raise ValueError("Телефон должен содержать не менее 10 цифр")
        return v


class TeacherOut(TeacherBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ---------- Subjects ----------


class SubjectBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    teacher_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Название предмета не может быть пустым")
        return v


class SubjectCreate(SubjectBase):
    pass


class SubjectUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    teacher_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = " ".join(v.split())
        if not v:
            raise ValueError("Название предмета не может быть пустым")
        return v


class SubjectOut(SubjectBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ---------- Students ----------


class StudentBase(BaseModel):
    fio: str = Field(..., min_length=5, max_length=200)
    email: EmailStr
    group_id: Optional[int] = None
    enrollment_date: date = Field(default_factory=date.today)
    behavior_grade: Optional[int] = Field(None, ge=2, le=5)

    @field_validator("fio")
    @classmethod
    def validate_fio(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 5:
            raise ValueError("ФИО слишком короткое")
        if len(v.split()) < 2:
            raise ValueError("ФИО должно содержать как минимум имя и фамилию")
        return v

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).lower()

    @field_validator("enrollment_date")
    @classmethod
    def validate_enrollment_date(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("Дата зачисления не может быть в будущем")
        return v


class StudentCreate(StudentBase):
    pass


class StudentUpdate(BaseModel):
    fio: Optional[str] = Field(None, min_length=5, max_length=200)
    email: Optional[EmailStr] = None
    group_id: Optional[int] = None
    enrollment_date: Optional[date] = None
    behavior_grade: Optional[int] = Field(None, ge=2, le=5)

    @field_validator("fio")
    @classmethod
    def validate_fio(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = " ".join(v.split())
        if len(v) < 5:
            raise ValueError("ФИО слишком короткое")
        if len(v.split()) < 2:
            raise ValueError("ФИО должно содержать как минимум имя и фамилию")
        return v

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: Optional[EmailStr]) -> Optional[str]:
        if v is None:
            return None
        return str(v).lower()

    @field_validator("enrollment_date")
    @classmethod
    def validate_enrollment_date(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return None
        if v > date.today():
            raise ValueError("Дата зачисления не может быть в будущем")
        return v


class StudentOut(StudentBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ---------- Behavior Records ----------


class BehaviorBase(BaseModel):
    student_id: int
    subject_id: Optional[int] = None
    record_date: date = Field(default_factory=date.today)
    points: float = Field(0.0, ge=0, le=100)
    remark: Optional[str] = Field(None, max_length=500)
    is_unexcused_absence: bool = False

    @field_validator("record_date")
    @classmethod
    def validate_record_date(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("Дата записи о поведении не может быть в будущем")
        return v

    @field_validator("points")
    @classmethod
    def validate_points(cls, v: float) -> float:
        if v < 0 or v > 100:
            raise ValueError("Баллы поведения должны быть в диапазоне от 0 до 100")
        return float(v)


class BehaviorCreate(BehaviorBase):
    pass


class BehaviorUpdate(BaseModel):
    student_id: Optional[int] = None
    subject_id: Optional[int] = None
    record_date: Optional[date] = None
    points: Optional[float] = Field(None, ge=0, le=100)
    remark: Optional[str] = Field(None, max_length=500)
    is_unexcused_absence: Optional[bool] = None

    @field_validator("record_date")
    @classmethod
    def validate_record_date(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            return None
        if v > date.today():
            raise ValueError("Дата записи о поведении не может быть в будущем")
        return v

    @field_validator("points")
    @classmethod
    def validate_points(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if v < 0 or v > 100:
            raise ValueError("Баллы поведения должны быть в диапазоне от 0 до 100")
        return float(v)


class BehaviorOut(BehaviorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class BehaviorReportOut(BaseModel):
    student_id: int
    fio: str
    group_id: Optional[int]
    group_name: Optional[str]

    behavior_grade: Optional[int]
    max_allowed_grade: int

    unexcused_absences: int
    total_records: int
    total_points: float
    average_points: float

    is_limited_by_absences: bool
    recommendation: str

    records: List[BehaviorOut]


# =====================================================================
# FASTAPI APP
# =====================================================================


app = FastAPI(
    title="Практическая работа №8 — Вариант 7",
    version="1.0.0",
    description=(
        "Школа: CRUD для Student, Group, Subject, Teacher. "
        "Дополнительная сущность: BehaviorRecord — журнал поведения. "
        "Специфический GET: /api/students/{id}/behavior-report. "
        "Бизнес-правило: оценка за поведение не может быть выше 4, "
        "если пропусков без уважительной причины больше 3."
    ),
)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def commit_or_400(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка целостности данных: дубликат или недопустимая ссылка.",
        ) from exc


def get_or_404(db: Session, model, pk: int, entity: str):
    obj = db.get(model, pk)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity} не найден(а)",
        )
    return obj


def count_unexcused_absences(db: Session, student_id: int) -> int:
    result = db.scalar(
        select(func.count())
        .select_from(BehaviorRecord)
        .where(
            BehaviorRecord.student_id == student_id,
            BehaviorRecord.is_unexcused_absence.is_(True),
        )
    )
    return int(result or 0)


def apply_behavior_grade_cap(db: Session, student: Student) -> None:
    """
    Бизнес-правило варианта 7:
    если пропусков без уважительной причины больше 3,
    оценка за поведение не может быть выше 4.
    """
    absences = count_unexcused_absences(db, student.id)

    if (
        student.behavior_grade is not None
        and absences > 3
        and student.behavior_grade > 4
    ):
        student.behavior_grade = 4


# =====================================================================
# ОБРАБОТЧИКИ ОШИБОК
# =====================================================================


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        errors.append(
            {
                "loc": list(err.get("loc", [])),
                "msg": err.get("msg"),
                "type": err.get("type"),
            }
        )

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Ошибка валидации входных данных",
            "errors": errors,
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Ошибка целостности данных: дубликат или недопустимая ссылка.",
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Внутренняя серверная ошибка.",
        },
    )


# =====================================================================
# ROOT / HEALTH
# =====================================================================


@app.get("/", include_in_schema=False)
def root():
    return {
        "message": "School API variant 7 is running",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


# =====================================================================
# CRUD: GROUPS
# =====================================================================


@app.post("/api/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(Group).where(Group.name == payload.name))
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Класс/группа с таким названием уже существует",
        )

    group = Group(**payload.model_dump())
    db.add(group)
    commit_or_400(db)
    db.refresh(group)
    return group


@app.get("/api/groups", response_model=List[GroupOut])
def list_groups(db: Session = Depends(get_db)):
    return db.scalars(select(Group)).all()


@app.get("/api/groups/{group_id}", response_model=GroupOut)
def get_group(group_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Group, group_id, "Класс/группа")


@app.put("/api/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: int,
    payload: GroupUpdate,
    db: Session = Depends(get_db),
):
    group = get_or_404(db, Group, group_id, "Класс/группа")

    data = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }

    if "name" in data:
        exists = db.scalar(
            select(Group).where(Group.name == data["name"], Group.id != group_id)
        )
        if exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Класс/группа с таким названием уже существует",
            )

    for field, value in data.items():
        setattr(group, field, value)

    commit_or_400(db)
    db.refresh(group)
    return group


@app.delete("/api/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = get_or_404(db, Group, group_id, "Класс/группа")
    db.delete(group)
    commit_or_400(db)
    return None


# =====================================================================
# CRUD: TEACHERS
# =====================================================================


@app.post("/api/teachers", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
def create_teacher(payload: TeacherCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(Teacher).where(Teacher.email == payload.email))
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Преподаватель с таким email уже существует",
        )

    teacher = Teacher(**payload.model_dump())
    db.add(teacher)
    commit_or_400(db)
    db.refresh(teacher)
    return teacher


@app.get("/api/teachers", response_model=List[TeacherOut])
def list_teachers(db: Session = Depends(get_db)):
    return db.scalars(select(Teacher)).all()


@app.get("/api/teachers/{teacher_id}", response_model=TeacherOut)
def get_teacher(teacher_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Teacher, teacher_id, "Преподаватель")


@app.put("/api/teachers/{teacher_id}", response_model=TeacherOut)
def update_teacher(
    teacher_id: int,
    payload: TeacherUpdate,
    db: Session = Depends(get_db),
):
    teacher = get_or_404(db, Teacher, teacher_id, "Преподаватель")

    data = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }

    if "email" in data:
        exists = db.scalar(
            select(Teacher).where(
                Teacher.email == data["email"],
                Teacher.id != teacher_id,
            )
        )
        if exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Преподаватель с таким email уже существует",
            )

    for field, value in data.items():
        setattr(teacher, field, value)

    commit_or_400(db)
    db.refresh(teacher)
    return teacher


@app.delete("/api/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_teacher(teacher_id: int, db: Session = Depends(get_db)):
    teacher = get_or_404(db, Teacher, teacher_id, "Преподаватель")
    db.delete(teacher)
    commit_or_400(db)
    return None


# =====================================================================
# CRUD: SUBJECTS
# =====================================================================


@app.post("/api/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(Subject).where(Subject.title == payload.title))
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Предмет с таким названием уже существует",
        )

    if payload.teacher_id is not None:
        get_or_404(db, Teacher, payload.teacher_id, "Преподаватель")

    subject = Subject(**payload.model_dump())
    db.add(subject)
    commit_or_400(db)
    db.refresh(subject)
    return subject


@app.get("/api/subjects", response_model=List[SubjectOut])
def list_subjects(db: Session = Depends(get_db)):
    return db.scalars(select(Subject)).all()


@app.get("/api/subjects/{subject_id}", response_model=SubjectOut)
def get_subject(subject_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Subject, subject_id, "Предмет")


@app.put("/api/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int,
    payload: SubjectUpdate,
    db: Session = Depends(get_db),
):
    subject = get_or_404(db, Subject, subject_id, "Предмет")

    data = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }

    if "title" in data:
        exists = db.scalar(
            select(Subject).where(
                Subject.title == data["title"],
                Subject.id != subject_id,
            )
        )
        if exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Предмет с таким названием уже существует",
            )

    if "teacher_id" in data and data["teacher_id"] is not None:
        get_or_404(db, Teacher, data["teacher_id"], "Преподаватель")

    for field, value in data.items():
        setattr(subject, field, value)

    commit_or_400(db)
    db.refresh(subject)
    return subject


@app.delete("/api/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(subject_id: int, db: Session = Depends(get_db)):
    subject = get_or_404(db, Subject, subject_id, "Предмет")
    db.delete(subject)
    commit_or_400(db)
    return None


# =====================================================================
# CRUD: STUDENTS
# =====================================================================


@app.post("/api/students", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(payload: StudentCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(Student).where(Student.email == payload.email))
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ученик с таким email уже существует",
        )

    if payload.group_id is not None:
        get_or_404(db, Group, payload.group_id, "Класс/группа")

    student = Student(**payload.model_dump())
    db.add(student)
    commit_or_400(db)
    db.refresh(student)
    return student


@app.get("/api/students", response_model=List[StudentOut])
def list_students(
    group_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    stmt = select(Student)
    if group_id is not None:
        stmt = stmt.where(Student.group_id == group_id)
    return db.scalars(stmt).all()


@app.get(
    "/api/students/{student_id}/behavior-report",
    response_model=BehaviorReportOut,
    summary="Отчет о поведении для родителей",
)
def get_behavior_report(student_id: int, db: Session = Depends(get_db)):
    """
    Специфический GET для варианта 7.

    Возвращает родительский отчет:
    - оценка за поведение;
    - максимально допустимая оценка;
    - количество пропусков без уважительной причины;
    - список записей журнала поведения;
    - рекомендация.
    """
    student = get_or_404(db, Student, student_id, "Ученик")

    records = db.scalars(
        select(BehaviorRecord)
        .where(BehaviorRecord.student_id == student_id)
        .order_by(BehaviorRecord.record_date.desc(), BehaviorRecord.id.desc())
    ).all()

    absences = sum(1 for r in records if r.is_unexcused_absence)
    total_points = sum(float(r.points) for r in records)
    average_points = round(total_points / len(records), 2) if records else 0.0

    max_allowed_grade = 4 if absences > 3 else 5

    current_grade = student.behavior_grade
    effective_grade = (
        min(current_grade, max_allowed_grade)
        if current_grade is not None
        else None
    )

    is_limited = absences > 3

    if is_limited:
        recommendation = (
            f"Пропущено {absences} занятий без уважительной причины. "
            "Оценка за поведение не может быть выше 4."
        )
    elif effective_grade == 5:
        recommendation = "Поведение отличное. Замечаний минимум."
    elif effective_grade == 4:
        recommendation = "Поведение хорошее. Есть незначительные замечания."
    elif effective_grade == 3:
        recommendation = "Есть систематические замечания по поведению."
    elif effective_grade == 2:
        recommendation = "Требуется срочная работа над поведением."
    else:
        recommendation = "Оценка за поведение еще не выставлена."

    return BehaviorReportOut(
        student_id=student.id,
        fio=student.fio,
        group_id=student.group_id,
        group_name=student.group.name if student.group else None,
        behavior_grade=effective_grade,
        max_allowed_grade=max_allowed_grade,
        unexcused_absences=absences,
        total_records=len(records),
        total_points=round(total_points, 2),
        average_points=average_points,
        is_limited_by_absences=is_limited,
        recommendation=recommendation,
        records=[BehaviorOut.model_validate(r) for r in records],
    )


@app.get("/api/students/{student_id}", response_model=StudentOut)
def get_student(student_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Student, student_id, "Ученик")


@app.put("/api/students/{student_id}", response_model=StudentOut)
def update_student(
    student_id: int,
    payload: StudentUpdate,
    db: Session = Depends(get_db),
):
    student = get_or_404(db, Student, student_id, "Ученик")

    data = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }

    if "email" in data:
        exists = db.scalar(
            select(Student).where(
                Student.email == data["email"],
                Student.id != student_id,
            )
        )
        if exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ученик с таким email уже существует",
            )

    if "group_id" in data and data["group_id"] is not None:
        get_or_404(db, Group, data["group_id"], "Класс/группа")

    # Бизнес-правило варианта 7 при явной установке оценки за поведение.
    if "behavior_grade" in data and data["behavior_grade"] is not None:
        absences = count_unexcused_absences(db, student.id)
        new_grade = int(data["behavior_grade"])

        if absences > 3 and new_grade > 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Оценка за поведение не может быть выше 4, "
                    "если пропусков без уважительной причины больше 3."
                ),
            )

    for field, value in data.items():
        setattr(student, field, value)

    # На всякий случай применяем ограничение после обновления.
    apply_behavior_grade_cap(db, student)

    commit_or_400(db)
    db.refresh(student)
    return student


@app.delete("/api/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_student(student_id: int, db: Session = Depends(get_db)):
    student = get_or_404(db, Student, student_id, "Ученик")
    db.delete(student)
    commit_or_400(db)
    return None


# =====================================================================
# CRUD: BEHAVIOR RECORDS
# =====================================================================


@app.post(
    "/api/behavior-records",
    response_model=BehaviorOut,
    status_code=status.HTTP_201_CREATED,
)
def create_behavior_record(
    payload: BehaviorCreate,
    db: Session = Depends(get_db),
):
    student = get_or_404(db, Student, payload.student_id, "Ученик")

    if payload.subject_id is not None:
        get_or_404(db, Subject, payload.subject_id, "Предмет")

    record = BehaviorRecord(**payload.model_dump())

    db.add(record)
    db.flush()

    # Если добавили пропуск без причины и их стало больше 3,
    # автоматически ограничиваем оценку за поведение до 4.
    apply_behavior_grade_cap(db, student)

    commit_or_400(db)
    db.refresh(record)
    return record


@app.get("/api/behavior-records", response_model=List[BehaviorOut])
def list_behavior_records(
    student_id: Optional[int] = Query(None, ge=1),
    subject_id: Optional[int] = Query(None, ge=1),
    unexcused_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    stmt = select(BehaviorRecord)

    if student_id is not None:
        stmt = stmt.where(BehaviorRecord.student_id == student_id)

    if subject_id is not None:
        stmt = stmt.where(BehaviorRecord.subject_id == subject_id)

    if unexcused_only:
        stmt = stmt.where(BehaviorRecord.is_unexcused_absence.is_(True))

    stmt = stmt.order_by(BehaviorRecord.record_date.desc(), BehaviorRecord.id.desc())

    return db.scalars(stmt).all()


@app.get("/api/behavior-records/{record_id}", response_model=BehaviorOut)
def get_behavior_record(record_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, BehaviorRecord, record_id, "Запись журнала поведения")


@app.put("/api/behavior-records/{record_id}", response_model=BehaviorOut)
def update_behavior_record(
    record_id: int,
    payload: BehaviorUpdate,
    db: Session = Depends(get_db),
):
    record = get_or_404(db, BehaviorRecord, record_id, "Запись журнала поведения")

    data = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }

    if "student_id" in data and data["student_id"] is not None:
        get_or_404(db, Student, data["student_id"], "Ученик")

    if "subject_id" in data and data["subject_id"] is not None:
        get_or_404(db, Subject, data["subject_id"], "Предмет")

    for field, value in data.items():
        setattr(record, field, value)

    db.flush()

    # После изменения записи пересчитываем ограничение по поведению.
    apply_behavior_grade_cap(db, record.student)

    commit_or_400(db)
    db.refresh(record)
    return record


@app.delete(
    "/api/behavior-records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_behavior_record(record_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, BehaviorRecord, record_id, "Запись журнала поведения")
    db.delete(record)
    commit_or_400(db)
    return None
