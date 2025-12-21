#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP_DIR="$SCRIPT_DIR/cleanup"
OUTPUT_FILE="$SCRIPT_DIR/cleanup.zip"

echo "Building Lambda deployment package..."

# Clean up any existing zip file
rm -f "$OUTPUT_FILE"

# Create a temporary directory for building
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Copy cleanup code
cp "$CLEANUP_DIR/cleanup.py" "$BUILD_DIR/"

# Install dependencies if requirements.txt exists
if [ -f "$CLEANUP_DIR/requirements.txt" ]; then
    echo "Installing dependencies..."
    pip install -r "$CLEANUP_DIR/requirements.txt" -t "$BUILD_DIR" --quiet
fi

# Create zip file
cd "$BUILD_DIR"
zip -r "$OUTPUT_FILE" . -q

echo "Lambda package created: $OUTPUT_FILE"

