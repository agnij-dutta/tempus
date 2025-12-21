import logging
import os
from contextlib import asynccontextmanager

import boto3
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from app.routes import preview

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# AWS clients (will be configured via IAM roles in ECS)
# These are initialized here but will be used by services
ecs_client = None
dynamodb_client = None
elbv2_client = None
eventbridge_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    global ecs_client, dynamodb_client, elbv2_client, eventbridge_client
    
    # Initialize AWS clients
    region = os.getenv("AWS_REGION", "ap-south-1")
    logger.info(f"Initializing AWS clients for region: {region}")
    
    ecs_client = boto3.client("ecs", region_name=region)
    dynamodb_client = boto3.client("dynamodb", region_name=region)
    elbv2_client = boto3.client("elbv2", region_name=region)
    eventbridge_client = boto3.client("events", region_name=region)
    
    logger.info("AWS clients initialized successfully")
    
    yield
    
    logger.info("Shutting down application")


app = FastAPI(
    title="Tempus",
    description="""
    ## Ephemeral Preview Environment Generator
    
    **Tempus** is a cost-aware system for dynamically provisioning short-lived preview environments on AWS.
    Each preview environment automatically destroys itself after a specified time period, ensuring no orphaned resources consume budget.
    
    ### Features
    
    - 🚀 **Dynamic Provisioning**: Create preview environments on-demand
    - ⏱️ **Automatic Cleanup**: TTL-based automatic resource teardown
    - 💰 **Cost-Effective**: Pay only for what you use, when you use it
    - 🔒 **Secure**: Built on AWS with IAM-based security
    
    ### Quick Start
    
    1. Create a preview environment with `POST /preview/create`
    2. Use the returned preview URL to access your environment
    3. The environment automatically cleans up after the TTL expires
    
    ### Architecture
    
    - **Backend**: FastAPI (Python)
    - **Infrastructure**: Terraform + AWS
    - **Compute**: ECS Fargate
    - **Database**: DynamoDB
    - **Cleanup**: EventBridge + Lambda
    """,
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={
        "deepLinking": True,
        "displayRequestDuration": True,
        "filter": True,
        "showExtensions": True,
        "showCommonExtensions": True,
    }
)

# Mount static files for custom CSS/JS
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Middleware to inject custom CSS/JS into Swagger UI
@app.middleware("http")
async def add_custom_assets(request: Request, call_next):
    """Inject custom CSS and JS into Swagger UI."""
    response = await call_next(request)
    
    if request.url.path == "/docs" and response.status_code == 200:
        if hasattr(response, 'body'):
            html = response.body.decode('utf-8')
            
            # Inject custom CSS
            custom_css = '<link rel="stylesheet" type="text/css" href="/static/custom-swagger.css">'
            if '</head>' in html and custom_css not in html:
                html = html.replace('</head>', f'    {custom_css}\n</head>')
            
            # Inject custom JS
            custom_js = '<script src="/static/custom-swagger.js"></script>'
            if '</body>' in html and custom_js not in html:
                html = html.replace('</body>', f'    {custom_js}\n</body>')
            
            return HTMLResponse(content=html, status_code=response.status_code)
    
    return response

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(preview.router)


@app.get("/health", tags=["default"], summary="Root Health Check")
async def health():
    """
    Root health check endpoint.
    
    Returns the overall service status. Use this to verify the API is running and accessible.
    """
    return {"status": "ok", "service": "tempus"}
