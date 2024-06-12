# syntax=docker/dockerfile:1

# Comments are provided throughout this file to help you get started.
# If you need more help, visit the Dockerfile reference guide at
# https://docs.docker.com/go/dockerfile-reference/

# Want to help us make this template better? Share your feedback here: https://forms.gle/ybq9Krt8jtBL3iCk7

ARG PYTHON_VERSION=3.11.8
FROM python:${PYTHON_VERSION}-slim as base

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

# Setup Poetry environment variables.
ENV POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_IN_PROJECT=1 \
  POETRY_VIRTUALENVS_CREATE=1 \
  POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg

RUN pip install poetry==1.4.2

COPY pyproject.toml poetry.lock ./

# Install the application's dependencies without the application source code
# to avoid rebuilding dependencies when the source code changes.
RUN poetry install --without dev --no-root && rm -rf $POETRY_CACHE_DIR

# Copy the source code into the container.
COPY . .

# Create a non-privileged user that the app will run under.
# See https://docs.docker.com/go/dockerfile-user-best-practices/
ARG UID=10001
RUN adduser \
  --disabled-password \
  --uid "${UID}" \
  appuser

# Switch to the non-privileged user to run the application.
USER appuser

# Run the application.
CMD poetry run python main.py start
