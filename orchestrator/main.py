# orchestrator/main.py
import os
import uuid
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

import redis
import asyncpg
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Models
class AuditRequest(BaseModel):
    cloud_provider: str = Field(..., regex="^(azure|aws|gcp)$")
    subscription_id: Optional[str] = None
    account_id: Optional[str] = None
    project_id: Optional[str] = None
    checks: List[str] = Field(default=["security", "compliance"])
    priority: str = Field(default="medium", regex="^(low|medium|high)$")

class AuditJobResponse(BaseModel):
    job_id: str
    status: str
    message: str
    queue_position: Optional[int] = None

class HealthResponse(BaseModel):
    status: str
    redis: bool
    postgres: bool
    version: str = "1.0.0"
    uptime: float

# Global connections
redis_pool = None
pg_pool = None
start_time = datetime.now()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global redis_pool, pg_pool
    
    # Initialize Redis
    try:
        redis_pool = redis.ConnectionPool(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
            max_connections=20
        )
        r = redis.Redis(connection_pool=redis_pool)
        r.ping()
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        redis_pool = None
    
    # Initialize PostgreSQL
    try:
        pg_pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "auditdb"),
            user=os.getenv("POSTGRES_USER", "audituser"),
            password=os.getenv("POSTGRES_PASSWORD", "auditpass"),
            min_size=5,
            max_size=20
        )
        async with pg_pool.acquire() as conn:
            await conn.fetch("SELECT 1")
        logger.info("PostgreSQL connected successfully")
    except Exception as e:
        logger.error(f"PostgreSQL connection failed: {e}")
        pg_pool = None
    
    yield
    
    # Shutdown
    if redis_pool:
        redis_pool.disconnect()
    if pg_pool:
        await pg_pool.close()

# Create FastAPI app
app = FastAPI(
    title="Agentic Cloud Auditor",
    description="Minimal deployable cloud auditing system",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_redis():
    if not redis_pool:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return redis.Redis(connection_pool=redis_pool)

async def get_pg_connection():
    if not pg_pool:
        raise HTTPException(status_code=503, detail="PostgreSQL unavailable")
    return pg_pool

@app.get("/health", response_model=HealthResponse)
async def health_check():
    redis_ok = False
    postgres_ok = False
    
    # Check Redis
    if redis_pool:
        try:
            r = redis.Redis(connection_pool=redis_pool)
            redis_ok = r.ping()
        except:
            redis_ok = False
    
    # Check PostgreSQL
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                await conn.fetch("SELECT 1")
            postgres_ok = True
        except:
            postgres_ok = False
    
    uptime = (datetime.now() - start_time).total_seconds()
    
    return HealthResponse(
        status="healthy" if redis_ok and postgres_ok else "degraded",
        redis=redis_ok,
        postgres=postgres_ok,
        uptime=uptime
    )

@app.post("/audit", response_model=AuditJobResponse)
async def create_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    """Create a new audit job"""
    # Generate job ID
    job_id = f"audit_{uuid.uuid4().hex[:8]}"
    
    # Validate cloud-specific IDs
    if request.cloud_provider == "azure" and not request.subscription_id:
        raise HTTPException(status_code=400, detail="subscription_id required for Azure")
    elif request.cloud_provider == "aws" and not request.account_id:
        raise HTTPException(status_code=400, detail="account_id required for AWS")
    elif request.cloud_provider == "gcp" and not request.project_id:
        raise HTTPException(status_code=400, detail="project_id required for GCP")
    
    # Create job in database
    try:
        async with (await get_pg_connection()).acquire() as conn:
            await conn.execute("""
                INSERT INTO audit_jobs 
                (job_id, cloud_provider, subscription_id, account_id, project_id, checks, status)
                VALUES ($1, $2, $3, $4, $5, $6, 'pending')
            """, job_id, request.cloud_provider, request.subscription_id, 
                request.account_id, request.project_id, request.checks)
    except Exception as e:
        logger.error(f"Failed to create job in database: {e}")
        raise HTTPException(status_code=500, detail="Failed to create audit job")
    
    # Create audit tasks
    tasks = []
    for check in request.checks:
        task = {
            "job_id": job_id,
            "cloud_provider": request.cloud_provider,
            "subscription_id": request.subscription_id,
            "account_id": request.account_id,
            "project_id": request.project_id,
            "check_type": check,
            "priority": request.priority
        }
        tasks.append(task)
    
    # Queue tasks in Redis
    r = get_redis()
    queue_name = f"audit_queue_{request.priority}"
    
    try:
        for task in tasks:
            r.lpush(queue_name, json.dumps(task))
        
        # Get queue position
        queue_len = r.llen(queue_name)
        
        # Update job status
        async with (await get_pg_connection()).acquire() as conn:
            await conn.execute(
                "UPDATE audit_jobs SET status = 'queued' WHERE job_id = $1",
                job_id
            )
        
        # Start background processing
        background_tasks.add_task(process_audit_tasks)
        
        return AuditJobResponse(
            job_id=job_id,
            status="queued",
            message=f"Audit job created with {len(tasks)} tasks",
            queue_position=queue_len
        )
    except Exception as e:
        logger.error(f"Failed to queue tasks: {e}")
        async with (await get_pg_connection()).acquire() as conn:
            await conn.execute(
                "UPDATE audit_jobs SET status = 'failed', error_message = $1 WHERE job_id = $2",
                str(e), job_id
            )
        raise HTTPException(status_code=500, detail="Failed to queue audit tasks")

async def process_audit_tasks():
    """Background task to monitor and process audit tasks"""
    logger.info("Audit task processor started")
    while True:
        try:
            await asyncio.sleep(5)  # Check every 5 seconds
            # In a real implementation, this would trigger workers
            pass
        except Exception as e:
            logger.error(f"Error in task processor: {e}")
            await asyncio.sleep(30)

@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get status of an audit job"""
    try:
        async with (await get_pg_connection()).acquire() as conn:
            job = await conn.fetchrow(
                "SELECT * FROM audit_jobs WHERE job_id = $1",
                job_id
            )
            
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            
            findings = await conn.fetch(
                "SELECT COUNT(*) as count FROM audit_findings WHERE job_id = $1",
                job_id
            )
            
            return {
                "job_id": job["job_id"],
                "status": job["status"],
                "cloud_provider": job["cloud_provider"],
                "created_at": job["created_at"],
                "started_at": job["started_at"],
                "completed_at": job["completed_at"],
                "findings_count": findings[0]["count"] if findings else 0
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve job status")

@app.get("/jobs/{job_id}/findings")
async def get_job_findings(job_id: str, severity: Optional[str] = None):
    """Get findings for a job"""
    try:
        async with (await get_pg_connection()).acquire() as conn:
            # Verify job exists
            job = await conn.fetchrow(
                "SELECT job_id FROM audit_jobs WHERE job_id = $1",
                job_id
            )
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            
            # Build query
            query = "SELECT * FROM audit_findings WHERE job_id = $1"
            params = [job_id]
            
            if severity:
                query += " AND severity = $2"
                params.append(severity)
            
            query += " ORDER BY created_at DESC"
            
            findings = await conn.fetch(query, *params)
            
            return {
                "job_id": job_id,
                "findings": [
                    {
                        "id": f["id"],
                        "resource_id": f["resource_id"],
                        "resource_type": f["resource_type"],
                        "check_type": f["check_type"],
                        "severity": f["severity"],
                        "description": f["description"],
                        "recommendation": f["recommendation"],
                        "created_at": f["created_at"]
                    }
                    for f in findings
                ]
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get findings: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve findings")

@app.get("/metrics")
async def get_metrics():
    """Get system metrics"""
    try:
        r = get_redis()
        
        # Get queue lengths
        high_queue_len = r.llen("audit_queue_high") or 0
        medium_queue_len = r.llen("audit_queue_medium") or 0
        low_queue_len = r.llen("audit_queue_low") or 0
        
        # Get database stats
        async with (await get_pg_connection()).acquire() as conn:
            job_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_jobs,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_jobs,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_jobs
                FROM audit_jobs
            """)
            
            finding_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_findings,
                    COUNT(CASE WHEN severity = 'high' THEN 1 END) as high_findings,
                    COUNT(CASE WHEN severity = 'medium' THEN 1 END) as medium_findings,
                    COUNT(CASE WHEN severity = 'low' THEN 1 END) as low_findings
                FROM audit_findings
            """)
        
        return {
            "queues": {
                "high": high_queue_len,
                "medium": medium_queue_len,
                "low": low_queue_len
            },
            "jobs": dict(job_stats) if job_stats else {},
            "findings": dict(finding_stats) if finding_stats else {},
            "uptime": (datetime.now() - start_time).total_seconds()
        }
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metrics")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)