# Architecture Documentation

## Overview

Tempus is an ephemeral preview environment generator that dynamically provisions short-lived preview environments on AWS. Each preview environment automatically destroys itself after a specified time period, ensuring cost-effective infrastructure usage.

## System Architecture

### High-Level Flow

```
┌─────────┐
│ Client  │
└────┬────┘
     │ POST /create-preview
     │ {ttl_hours: 2}
     ▼
┌─────────────────────┐
│  FastAPI Backend    │
│  (ECS Fargate)      │
└────┬────────────────┘
     │
     ├──► Create ECS Service
     │    ├──► Task Definition
     │    ├──► Target Group
     │    └──► Service Registration
     │
     ├──► Store Metadata
     │    └──► DynamoDB
     │
     └──► Schedule Cleanup
          └──► EventBridge Rule
               │
               │ (at expires_at)
               ▼
          ┌─────────────────┐
          │ Cleanup Lambda  │
          └────────┬────────┘
                   │
                   ├──► Delete ECS Service
                   ├──► Delete Target Group
                   ├──► Delete EventBridge Rule
                   └──► Delete DynamoDB Record
```

## Components

### 1. FastAPI Backend

**Location**: `backend/app/`

**Responsibilities**:
- Accept preview creation requests
- Coordinate resource creation
- Store metadata
- Schedule cleanup events

**Key Files**:
- `main.py`: FastAPI application setup
- `routes/preview.py`: Preview creation endpoint
- `services/ecs_service.py`: ECS resource management
- `services/dynamodb_service.py`: Metadata storage
- `services/eventbridge_service.py`: Cleanup scheduling

### 2. ECS Fargate Service

**Purpose**: Run the FastAPI backend application

**Configuration**:
- Launch Type: Fargate
- CPU: 256 (0.25 vCPU)
- Memory: 512 MB
- Network: awsvpc mode
- Logging: CloudWatch Logs

### 3. Application Load Balancer (ALB)

**Purpose**: Provide public access to preview environments

**Features**:
- Path-based routing (`/preview-{preview_id}/*`)
- Health checks
- Target group per preview

### 4. DynamoDB

**Purpose**: Store preview metadata

**Schema**:
- Primary Key: `preview_id` (String)
- Attributes:
  - `service_arn`: ECS service ARN
  - `target_group_arn`: ALB target group ARN
  - `expires_at`: ISO timestamp
  - `created_at`: ISO timestamp
  - `eventbridge_rule_name`: Cleanup rule name

**Indexes**:
- GSI on `expires_at` for querying by expiration time

### 5. EventBridge

**Purpose**: Schedule cleanup events

**Implementation**:
- One rule per preview environment
- Scheduled at `expires_at` timestamp
- Triggers Lambda cleanup function

### 6. Lambda Cleanup Function

**Purpose**: Clean up preview environment resources

**Process**:
1. Fetch metadata from DynamoDB
2. Delete ECS service (scale to 0, then delete)
3. Delete ALB target group
4. Delete EventBridge rule
5. Delete DynamoDB record

## Data Flow

### Preview Creation Flow

1. **Client Request**
   - POST `/create-preview` with `ttl_hours`

2. **Backend Processing**
   - Generate `preview_id` (UUID)
   - Calculate `expires_at` = now + ttl_hours
   - Create ECS task definition
   - Create ALB target group
   - Create ECS service
   - Add ALB listener rule
   - Store metadata in DynamoDB
   - Create EventBridge rule

3. **Response**
   - Return `preview_id`, `preview_url`, `expires_at`

### Cleanup Flow

1. **EventBridge Trigger**
   - Rule fires at `expires_at`
   - Invokes Lambda function with `preview_id`

2. **Lambda Processing**
   - Fetch metadata from DynamoDB
   - Delete ECS service (wait for completion)
   - Delete target group
   - Delete EventBridge rule
   - Delete DynamoDB record

3. **Completion**
   - Log success/failure
   - Return status

## Security Considerations

### IAM Roles

1. **ECS Task Execution Role**
   - Pull images from ECR
   - Write logs to CloudWatch

2. **ECS Task Role**
   - Create/manage ECS services
   - Access DynamoDB
   - Manage ALB resources
   - Create EventBridge rules

3. **Lambda Execution Role**
   - Delete ECS services
   - Delete ALB target groups
   - Delete EventBridge rules
   - Access DynamoDB

### Network Security

- ALB security group: Allows HTTP/HTTPS from internet
- ECS security group: Allows traffic only from ALB
- VPC isolation: Uses default VPC (can be customized)

### Data Security

- DynamoDB encryption at rest
- CloudWatch logs encryption
- No hardcoded credentials (uses IAM roles)

## Cost Optimization

1. **DynamoDB**: Pay-per-request billing (no idle costs)
2. **ECS Fargate**: Pay only when running (no EC2 instances)
3. **Automatic Cleanup**: Prevents orphaned resources
4. **ECR Lifecycle Policy**: Removes old images automatically

## Scalability Considerations

### Current Limitations

- Single service per preview
- Single container per service
- No horizontal scaling

### Future Enhancements

- Multiple services per preview
- Auto-scaling based on load
- Multi-region support

## Monitoring and Observability

### CloudWatch Logs

- ECS task logs: `/ecs/tempus`
- Lambda logs: `/aws/lambda/tempus-cleanup`

### Metrics (Future)

- Preview creation count
- Cleanup success/failure rate
- Active preview count
- Resource utilization

## Error Handling

### Idempotency

- All operations are idempotent
- Safe to retry failed operations
- Handles "already exists" and "not found" errors

### Partial Failure Recovery

- If creation fails, cleanup created resources
- Lambda cleanup handles missing resources gracefully
- Logs all errors for debugging

## Deployment

See [deployment.md](deployment.md) for detailed deployment instructions.

