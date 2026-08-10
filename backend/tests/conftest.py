import pytest
import sys
import os

# Add the parent directory to sys.path to allow imports from the backend package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Define fixtures that can be used across tests
@pytest.fixture
def test_app():
    from backend.main import app
    return app