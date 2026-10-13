import os

os.environ.setdefault("DEMO_MODE", "false")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("HASH_ITERATIONS", "1000")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("HUMAN_REVIEW_EXPOSURE_THRESHOLD", "1000000")
