FROM python:3.12-slim

# System packages:
#  - can-utils: candump/cansend for debugging inside the container
#  - iproute2: ip command (for network diagnostics if needed)
#  - build-essential: sometimes needed for building python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    can-utils \
    iproute2 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# First, copy only dependencies so Docker caches this layer
# and doesn't reinstall when code changes
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Now copy the project code
COPY src/ ./src/
COPY tests/ ./tests/
COPY dbc/ ./dbc/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Copy conftest.py only if it exists (it may not exist at your stage)
COPY conftest.py* ./

# Install our project in editable mode
RUN pip install --no-cache-dir -e .

# PYTHONUNBUFFERED=1 so logs appear immediately without buffering
# PYTHONPATH tells where to look for our packages
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Default command - run the simulator
CMD ["python", "scripts/run_simulator.py", "--channel", "vcan0"]