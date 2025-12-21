# Tempus - Ephemeral Preview Environment Generator

## Problem

Developers need preview environments to test changes without burning money on idle infrastructure. Traditional preview environments often remain running indefinitely, leading to unnecessary costs.

## Solution

Tempus is a cost-aware ephemeral preview environment system that dynamically provisions short-lived preview environments on AWS with automatic teardown. Each preview environment automatically destroys itself after a specified time period, ensuring no orphaned resources consume budget.

## Architecture

```
Client
  |
  | POST /preview/create
  v
FastAPI Backend
  |
  ├──> Store Metadata (DynamoDB)
  ├──> Deploy Service (ECS Fargate)
  └──> Schedule Cleanup (EventBridge)
        |
        └──> Lambda → Destroy Resources
```

## Tech Stack

- **Backend**: Python + FastAPI
- **Infrastructure**: Terraform
- **Compute**: AWS ECS Fargate
- **Load Balancer**: Application Load Balancer (ALB)
- **Database**: DynamoDB
- **Cleanup**: EventBridge + Lambda
- **Container Registry**: ECR

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured
- Terraform >= 1.0
- Docker
- Python 3.11+
- Make (optional, for convenience commands)

## Quick Start

1. **Initial Setup**
   ```bash
   make setup
   ```

2. **Build and Push Container Image**
   ```bash
   make build
   make push
   ```

3. **Deploy Infrastructure**
   ```bash
   make deploy
   ```

4. **Create a Preview Environment**
   ```bash
   curl -X POST http://<ALB_URL>/preview/create \
     -H "Content-Type: application/json" \
     -d '{"ttl_hours": 2}'
   ```

## API Documentation

### POST /preview/create

Creates a new ephemeral preview environment.

**Request:**
```json
{
  "ttl_hours": 2
}
```

**Response:**
```json
{
  "preview_id": "550e8400-e29b-41d4-a716-446655440000",
  "preview_url": "http://alb-123456789.us-east-1.elb.amazonaws.com/preview-550e8400",
  "expires_at": "2024-01-01T14:00:00Z"
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "ok"
}
```

## Tradeoffs and Design Decisions

- **ECS Fargate over EKS**: Simpler to manage, no cluster overhead, sufficient for MVP
- **DynamoDB over RDS**: Faster setup, pay-per-request billing, better for metadata storage
- **No Authentication**: MVP focuses on core functionality; auth can be added later
- **Default VPC**: Simplifies initial setup; can migrate to custom VPC later
- **Single Service per Preview**: Keeps scope focused; multi-service support can be added

## Future Improvements

- GitHub PR integration for automatic preview creation
- Authentication and authorization
- Cost dashboard and analytics
- Multiple services per preview environment
- Preview extension API
- Manual deletion endpoint
- Preview status endpoint
- Cost estimation per preview

## License

MIT

