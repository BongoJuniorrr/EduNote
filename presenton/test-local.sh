#!/bin/bash

# Local test script that mimics the GitHub Actions workflow
# Run this to test everything before pushing

# Get the script directory and ensure we're in the project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🧪 Running local tests (simulating GitHub Actions workflow)..."
echo "📁 Working directory: $(pwd)"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track test results
FAILED_TESTS=0

# Detect Python command and dependency manager
if command -v uv &> /dev/null; then
    PYTHON_MANAGER="uv"
    PYTHON_CMD="uv run python"
    echo -e "${YELLOW}Using uv for Python dependency management${NC}"
elif command -v python3 &> /dev/null; then
    PYTHON_MANAGER="pip"
    PYTHON_CMD="python3"
    echo -e "${YELLOW}Using python3 with pip${NC}"
elif command -v python &> /dev/null; then
    PYTHON_MANAGER="pip"
    PYTHON_CMD="python"
    echo -e "${YELLOW}Using python with pip${NC}"
else
    echo -e "${RED}✗ Python not found. Please install Python 3.11+${NC}"
    exit 1
fi

echo ""

# Function to run a test and track results
run_test() {
    local test_name=$1
    local test_command=$2
    local original_dir=$(pwd)
    
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}Testing: $test_name${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    # Run the test command, capture exit code
    cd "$SCRIPT_DIR"
    if eval "$test_command"; then
        echo -e "${GREEN}✓ $test_name passed${NC}"
        echo ""
        cd "$SCRIPT_DIR"
        return 0
    else
        echo -e "${RED}✗ $test_name failed${NC}"
        echo ""
        cd "$SCRIPT_DIR"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
}

# Test 1: Main FastAPI
if [ -d "servers/fastapi" ]; then
    run_test "Main FastAPI" "
    cd servers/fastapi && \
    if [ \"$PYTHON_MANAGER\" = \"uv\" ] && [ -f \"pyproject.toml\" ]; then
        echo 'Installing dependencies with uv...' && \
        uv sync --dev 2>&1 | tail -5 || true
    elif [ -f \"pyproject.toml\" ]; then
        echo 'Installing dependencies with pip...' && \
        $PYTHON_CMD -m pip install -e . 2>&1 | tail -5 || true && \
        $PYTHON_CMD -m pip install pytest pytest-asyncio pytest-cov 2>&1 | tail -5 || true
    fi && \
    export APP_DATA_DIRECTORY=/tmp/app_data && \
    export TEMP_DIRECTORY=/tmp/presenton && \
    export DATABASE_URL=sqlite+aiosqlite:///./test.db && \
    export DISABLE_ANONYMOUS_TRACKING=true && \
    export DISABLE_IMAGE_GENERATION=true && \
    export PYTHONPATH=\$(pwd) && \
    $PYTHON_CMD -m pytest tests/ -v --tb=short
    "
else
    echo -e "${YELLOW}⚠ servers/fastapi not found, skipping${NC}"
    echo ""
fi

# Test 2: Electron FastAPI
if [ -d "electron/servers/fastapi" ]; then
    run_test "Electron FastAPI" "
    cd electron/servers/fastapi && \
    if [ \"$PYTHON_MANAGER\" = \"uv\" ] && [ -f \"pyproject.toml\" ]; then
        echo 'Installing dependencies with uv...' && \
        uv sync --dev 2>&1 | tail -5 || true
    elif [ -f \"pyproject.toml\" ]; then
        echo 'Installing dependencies with pip...' && \
        $PYTHON_CMD -m pip install -e . 2>&1 | tail -5 || true && \
        $PYTHON_CMD -m pip install pytest pytest-asyncio pytest-cov 2>&1 | tail -5 || true
    fi && \
    export APP_DATA_DIRECTORY=/tmp/app_data && \
    export TEMP_DIRECTORY=/tmp/presenton && \
    export DATABASE_URL=sqlite+aiosqlite:///./test.db && \
    export DISABLE_ANONYMOUS_TRACKING=true && \
    export DISABLE_IMAGE_GENERATION=true && \
    export PYTHONPATH=\$(pwd) && \
    $PYTHON_CMD -m pytest tests/ -v --tb=short
    "
else
    echo -e "${YELLOW}⚠ electron/servers/fastapi not found, skipping${NC}"
    echo ""
fi

# Test 3: Main Next.js
if [ -d "servers/nextjs" ]; then
    run_test "Main Next.js (lint & build)" "
    cd servers/nextjs && \
    if [ ! -d \"node_modules\" ]; then
        echo 'Installing npm dependencies...' && \
        npm ci 2>&1 | tail -10 || npm install 2>&1 | tail -10
    fi && \
    export NEXT_PUBLIC_FAST_API=http://localhost:8000 && \
    export NEXT_PUBLIC_URL=http://localhost:3000 && \
    npm run lint && \
    npm run build
    "
else
    echo -e "${YELLOW}⚠ servers/nextjs not found, skipping${NC}"
    echo ""
fi

# Test 4: Electron Next.js
if [ -d "electron/servers/nextjs" ]; then
    run_test "Electron Next.js (lint & build)" "
    cd electron/servers/nextjs && \
    if [ ! -d \"node_modules\" ]; then
        echo 'Installing npm dependencies...' && \
        npm ci --legacy-peer-deps 2>&1 | tail -10 || npm install --legacy-peer-deps 2>&1 | tail -10
    fi && \
    export NEXT_PUBLIC_FAST_API=http://localhost:8000 && \
    export NEXT_PUBLIC_URL=http://localhost:3000 && \
    npm run lint -- --legacy-peer-deps 2>&1 || npm run lint 2>&1 && \
    npm run build
    "
else
    echo -e "${YELLOW}⚠ electron/servers/nextjs not found, skipping${NC}"
    echo ""
fi

# Test 5: Docker Build (optional, skip if Docker not available)
if command -v docker &> /dev/null && [ -f "Dockerfile" ]; then
    run_test "Docker Build" "
    docker build -t presenton:test -f Dockerfile . && \
    docker images | grep presenton:test
    "
else
    if [ ! -f "Dockerfile" ]; then
        echo -e "${YELLOW}⚠ Dockerfile not found, skipping Docker build test${NC}"
    else
        echo -e "${YELLOW}⚠ Docker not found, skipping Docker build test${NC}"
    fi
    echo ""
fi

# Summary
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed! Ready to push.${NC}"
    exit 0
else
    echo -e "${RED}❌ $FAILED_TESTS test(s) failed. Please fix before pushing.${NC}"
    exit 1
fi
