#!/bin/bash
# Test runner script for git-deploy-healer

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo -e "${BLUE}=== $1 ===${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Default values
TEST_TYPE="all"
VERBOSE=false
COVERAGE=false
MARKERS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        unit)
            TEST_TYPE="unit"
            shift
            ;;
        integration)
            TEST_TYPE="integration"
            shift
            ;;
        webhook)
            TEST_TYPE="webhook"
            shift
            ;;
        healer)
            TEST_TYPE="healer"
            shift
            ;;
        deployment)
            TEST_TYPE="deployment"
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -c|--coverage)
            COVERAGE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [test_type] [options]"
            echo ""
            echo "Test types:"
            echo "  unit           Run unit tests only"
            echo "  integration    Run integration tests only"
            echo "  webhook        Run webhook integration tests"
            echo "  healer         Run healer recovery tests"
            echo "  deployment     Run deployment flow tests"
            echo "  all            Run all tests (default)"
            echo ""
            echo "Options:"
            echo "  -v, --verbose  Verbose output"
            echo "  -c, --coverage Generate coverage report"
            echo "  -h, --help     Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 unit                    # Run unit tests"
            echo "  $0 integration -v          # Run integration tests verbosely"
            echo "  $0 webhook -c              # Run webhook tests with coverage"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build pytest command
PYTEST_CMD="pytest"

# Add verbosity
if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -vv"
else
    PYTEST_CMD="$PYTEST_CMD -v"
fi

# Add coverage
if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=api --cov=core --cov-report=html --cov-report=term-missing"
fi

# Run tests based on type
case $TEST_TYPE in
    unit)
        print_header "Running Unit Tests"
        $PYTEST_CMD tests/unit/
        print_success "Unit tests completed"
        ;;
    integration)
        print_header "Running Integration Tests"
        print_warning "Make sure docker-compose.test.yml is available"
        RUN_INTEGRATION=1 $PYTEST_CMD tests/integration/
        print_success "Integration tests completed"
        ;;
    webhook)
        print_header "Running Webhook Integration Tests"
        print_warning "Make sure docker-compose.test.yml is available"
        RUN_INTEGRATION=1 $PYTEST_CMD tests/integration/test_webhook_to_deploy.py
        print_success "Webhook tests completed"
        ;;
    healer)
        print_header "Running Healer Recovery Tests"
        print_warning "Make sure docker-compose.test.yml is available"
        RUN_INTEGRATION=1 $PYTEST_CMD tests/integration/test_healer_recovery.py
        print_success "Healer tests completed"
        ;;
    deployment)
        print_header "Running Deployment Flow Tests"
        print_warning "Make sure docker-compose.test.yml is available"
        RUN_INTEGRATION=1 $PYTEST_CMD tests/integration/test_deployment_flow.py
        print_success "Deployment tests completed"
        ;;
    all)
        print_header "Running All Tests"

        # Run unit tests first
        print_header "Step 1: Unit Tests"
        $PYTEST_CMD tests/unit/
        print_success "Unit tests passed"

        # Run integration tests
        print_header "Step 2: Integration Tests"
        if [ -f "docker-compose.test.yml" ]; then
            RUN_INTEGRATION=1 $PYTEST_CMD tests/integration/
            print_success "Integration tests passed"
        else
            print_warning "docker-compose.test.yml not found, skipping integration tests"
        fi

        print_success "All tests completed"
        ;;
esac

# Print coverage report location if generated
if [ "$COVERAGE" = true ]; then
    print_header "Coverage Report"
    echo "HTML report: htmlcov/index.html"
    if command -v xdg-open &> /dev/null; then
        read -p "Open coverage report? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            xdg-open htmlcov/index.html
        fi
    fi
fi

print_success "Done!"
