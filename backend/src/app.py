"""
TaskFlow Backend - FastAPI Task Management Service

A RESTful API for task management with TDD approach.

TP 1 & 2: Uses in-memory storage for simplicity
TP 3: Will introduce PostgreSQL database (see migration guide)
"""

from typing import List, Optional, Dict
from datetime import datetime, timezone
from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import logging

from contextlib import asynccontextmanager
import uuid
from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from .database import get_db, init_db
from .models import TaskModel, TaskStatus, TaskPriority

from fastapi.middleware.cors import CORSMiddleware
import os



# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("taskflow")


# =============================================================================
# ENUMS & MODELS
# =============================================================================

class TaskCreate(BaseModel):
    """Model for creating a new task."""
    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, max_length=1000, description="Task description")
    status: TaskStatus = Field(default=TaskStatus.TODO, description="Task status")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Task priority")
    assignee: Optional[str] = Field(None, max_length=100, description="Assigned user")
    due_date: Optional[datetime] = Field(None, description="Due date")


class TaskUpdate(BaseModel):
    """Model for updating a task - all fields optional for partial updates."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee: Optional[str] = Field(None, max_length=100)
    due_date: Optional[datetime] = None


class Task(BaseModel):
    """Model for task response."""
    id: str  # ← Changé en str pour UUID
    title: str
    description: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    assignee: Optional[str] = None
    due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Permet la conversion depuis SQLAlchemy


# =============================================================================
# IN-MEMORY STORAGE (for Atelier 1 & 2)
# =============================================================================

# Simple dictionary to store tasks
# In Atelier 3, this will be replaced with PostgreSQL database

# =============================================================================
# FASTAPI APP
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager - initialise la DB au démarrage."""
    logger.info("🚀 TaskFlow backend starting up...")
    init_db()  # Crée les tables
    logger.info("✅ Database initialized")
    yield
    logger.info("🛑 TaskFlow backend shutting down...")


app = FastAPI(
    title="TaskFlow API",
    description="Simple task management API for learning unit testing and CI/CD",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,  # ← Ajouter cette ligne
)

# Configuration CORS pour le frontend
cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
cors_origins = [origin.strip() for origin in cors_origins_str.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root(db: Session = Depends(get_db)):
    """API root endpoint."""
    return {
        "message": "Welcome to TaskFlow API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check with database status."""
    try:
        db.execute(text("SELECT 1"))
        tasks_count = db.query(TaskModel).count()
        return {
            "status": "healthy",
            "database": "connected",
            "tasks_count": tasks_count
        }
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/tasks", response_model=List[Task])
async def get_tasks(
    status: Optional[TaskStatus] = None,
    priority: Optional[TaskPriority] = None,
    assignee: Optional[str] = None,
    db: Session = Depends(get_db)  # ← Toujours en dernier dans les paramètres
):
    """Get all tasks with optional filtering."""
    query = db.query(TaskModel)

    if status:
        query = query.filter(TaskModel.status == status)
    if priority:
        query = query.filter(TaskModel.priority == priority)
    if assignee:
        query = query.filter(TaskModel.assignee == assignee)

    return query.all()


@app.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str, db: Session = Depends(get_db)):
    """Get a single task by ID."""
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@app.post("/tasks", response_model=Task, status_code=201)
async def create_task(task_data: TaskCreate, db: Session = Depends(get_db)) -> Task:
    # 1. Validation du titre
    if not task_data.title or not task_data.title.strip():
        raise HTTPException(status_code=422, detail="Le titre ne peut pas être vide.")

    # 2. Création de l'objet TaskModel (SQLAlchemy)
    
    # Nous utilisons 'uuid.uuid4()' pour générer un ID unique,
    # et 'datetime.now(timezone.utc)' pour un horodatage précis.
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # Map des données Pydantic à l'objet SQLAlchemy TaskModel
    db_task = TaskModel(
        id=task_id, # Utilisation de l'UUID généré
        title=task_data.title,
        description=task_data.description,
        status=task_data.status,
        priority=task_data.priority,
        assignee=task_data.assignee,
        due_date=task_data.due_date
    )
    
    # 3. Opérations sur la base de données
    db.add(db_task)
    try:
        db.commit() # Tente d'écrire la tâche dans la base de données
    except Exception as e:
        db.rollback() # Annule les changements en cas d'erreur
        # Vous pourriez vouloir logguer l'erreur ici : logger.error(f"DB Error: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde de la tâche dans la base de données.")

    db.refresh(db_task) # Récupère la tâche fraîchement créée (incluant les valeurs par défaut DB si elles existent)

    # 4. Enregistrement (Logging) et Retour
    
    # Ligne originale non nécessaire si on utilise uniquement la DB: tasks_db[task_id] = task
    # Ligne de log
    # logger.info(f"Task created successfully: {task_id}") 
    
    # Construction du modèle de retour Pydantic (Task) à partir de l'objet SQLAlchemy (db_task)
    return db_task 
    # ou Task(**db_task.__dict__) si Task.from_orm n'est pas configuré


@app.put("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: int, updates: TaskUpdate,db: Session = Depends(get_db)) -> Task:
    """
    Update an existing task (partial update supported).

    TODO (Atelier 1 - Exercice 2): Implémenter cette fonction

    Étapes à suivre:
    1. Vérifier que la tâche existe dans tasks_db
       - Si elle n'existe pas, lever HTTPException(status_code=404, detail=f"Task {task_id} not found")

    2. Récupérer la tâche existante

    3. Extraire les champs à mettre à jour avec updates.model_dump(exclude_unset=True)

    4. Valider le titre s'il est fourni (ne doit pas être vide)
       - Si vide, lever HTTPException(status_code=422, detail="Title cannot be empty")

    5. Créer une nouvelle Task avec:
       - Les champs mis à jour (utiliser update_data.get("field", existing_task.field))
       - created_at = existing_task.created_at (ne change pas)
       - updated_at = datetime.utcnow() (nouvelle date)

    6. Mettre à jour tasks_db[task_id]

    7. Retourner la tâche mise à jour

    Indice: Regardez comment create_task fonctionne pour vous inspirer
    """
    tasks_db = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    
    if tasks_db is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    # TODO: Votre code ici
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    
    existing_task = tasks_db[task_id]
    update_data = updates.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(task, field, value)

    if not existing_task.title or not existing_task.title.strip():
        raise HTTPException(status_code=422, detail="Title cannot be empty")
    
    task = Task(
        id=update_data.get("id",existing_task.id),
        title=update_data.get("title",existing_task.title),
        description=update_data.get("description",existing_task.description),
        status=update_data.get("status",existing_task.status),
        priority=update_data.get("priority",existing_task.priority),
        assignee=update_data.get("assignee",existing_task.assignee),
        due_date=update_data.get("due_date",existing_task.due_date),
        created_at=existing_task.created_at,
        updated_at=datetime.utcnow(),   
    )

    db.commit()
    db.refresh(task)

    tasks_db[task_id] = task
    logger.info(f"Task updated successfully: {task_id}")
    return task
    

@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, db: Session = Depends(get_db)):
    """Delete a task by ID."""
    task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    db.delete(task)
    db.commit()

    logger.info(f"Task deleted successfully: {task_id}")
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)