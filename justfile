# Build the frontend and backend
build:
    cd frontend && pnpm build

# Serve the frontend and backend in development mode
dev:
    #!/usr/bin/env bash
    set -euo pipefail

    (cd frontend && pnpm dev) &
    frontend_pid=$!

    cleanup() {
        local status=$?
        trap - EXIT INT TERM

        kill "$frontend_pid" 2>/dev/null || true
        wait "$frontend_pid" 2>/dev/null || true

        exit "$status"
    }

    trap cleanup EXIT INT TERM

    uv run pos-service -d

# Install dependencies for the frontend and backend
install:
    cd frontend && pnpm install
    uv sync

# Run the backend tests
test:
    uv run pytest
