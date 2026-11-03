# Build the frontend and backend
build:
    cd frontend && pnpm build

# Serve the frontend and backend in development mode
dev:
    cd frontend && pnpm dev &
    uv run pos -d

# Install dependencies for the frontend and backend
install:
    cd frontend && pnpm install
    uv sync

# Run the backend tests
test:
    uv run pytest
