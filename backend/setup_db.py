import asyncio
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get database URL from environment or use default
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sentryflow")

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for declarative models
Base = declarative_base()

# Import models to ensure they're registered with Base
from models.user import User
from models.api_key import ApiKey
from models.rate_limit import RateLimit


def init_db():
    """Initialize the database by creating all tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")


def create_admin_user():
    """Create an admin user if it doesn't exist."""
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    db = SessionLocal()
    try:
        # Check if admin user exists
        admin = db.query(User).filter(User.email == "admin@sentryflow.com").first()
        if not admin:
            print("Creating admin user...")
            # Create admin user
            admin_user = User(
                email="admin@sentryflow.com",
                username="admin",
                hashed_password=pwd_context.hash("admin123"),  # Change in production
                is_active=True,
                is_admin=True
            )
            db.add(admin_user)
            db.commit()
            print("Admin user created successfully!")
        else:
            print("Admin user already exists.")
    except Exception as e:
        db.rollback()
        print(f"Error creating admin user: {e}")
    finally:
        db.close()


def setup_default_rate_limits():
    """Set up default rate limits if they don't exist."""
    db = SessionLocal()
    try:
        # Check if default rate limit exists
        default_limit = db.query(RateLimit).filter(RateLimit.is_default == True).first()
        if not default_limit:
            print("Setting up default rate limits...")
            # Create default rate limit
            default_rate_limit = RateLimit(
                requests_per_window=int(os.getenv("DEFAULT_RATE_LIMIT", 100)),
                window_seconds=int(os.getenv("DEFAULT_RATE_LIMIT_WINDOW", 60)),
                algorithm=os.getenv("DEFAULT_RATE_LIMIT_ALGORITHM", "sliding_window"),
                is_default=True
            )
            db.add(default_rate_limit)
            db.commit()
            print("Default rate limits set up successfully!")
        else:
            print("Default rate limits already exist.")
    except Exception as e:
        db.rollback()
        print(f"Error setting up default rate limits: {e}")
    finally:
        db.close()


def main():
    """Main function to set up the database."""
    init_db()
    create_admin_user()
    setup_default_rate_limits()
    print("Database setup completed!")


if __name__ == "__main__":
    main()