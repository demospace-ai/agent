import os


def is_prod():
  return os.environ.get("ENVIRONMENT") != "production"
