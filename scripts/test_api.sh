#!/bin/bash
# Simple script to test the API endpoints

BASE_URL="${1:-http://localhost:8000}"

echo "Testing API at $BASE_URL"
echo ""

# Test health endpoint
echo "1. Testing GET /health"
curl -s "$BASE_URL/health" | jq '.' || echo "Failed"
echo ""

# Test root health
echo "2. Testing GET /health (root)"
curl -s "$BASE_URL/health" | jq '.' || echo "Failed"
echo ""

# Test preview creation (will fail without AWS, but tests the endpoint)
echo "3. Testing POST /preview/create"
echo "Request: {\"ttl_hours\": 2}"
curl -s -X POST "$BASE_URL/preview/create" \
  -H "Content-Type: application/json" \
  -d '{"ttl_hours": 2}' | jq '.' || echo "Failed"
echo ""

echo "Testing complete!"

