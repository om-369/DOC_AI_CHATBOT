import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-here')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Directory configuration
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    IMAGE_FOLDER = os.path.join(BASE_DIR, 'images')
    OUTPUT_TEXT_FOLDER = os.path.join(BASE_DIR, 'output_text')
    
    # Azure Cosmos DB configuration
    COSMOS_ENDPOINT = os.environ.get('COSMOS_ENDPOINT')
    COSMOS_KEY = os.environ.get('COSMOS_KEY')
    COSMOS_DB_NAME = os.environ.get('COSMOS_DB_NAME')
    COSMOS_CONTAINER_NAME = os.environ.get('COSMOS_CONTAINER_NAME')
    
    # Azure SQL Database configuration
    AZURE_SQL_CONN_STR = os.environ.get('AZURE_SQL_CONN_STR')
    
    # Google AI configuration
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    NOTEBOOK_API_URL = os.environ.get('NOTEBOOK_API_URL')
    COSMOSDB_CONNECTION_STRING = os.environ.get('COSMOSDB_CONNECTION_STRING')
    COSMOSDB_DATABASE_NAME = os.environ.get('COSMOSDB_DATABASE_NAME')
    COSMOSDB_CONTAINER_NAME = os.environ.get('COSMOSDB_CONTAINER_NAME')

    @staticmethod
    def init_app(app):
        # Create necessary directories
        for folder in [Config.UPLOAD_FOLDER, Config.IMAGE_FOLDER, Config.OUTPUT_TEXT_FOLDER]:
            os.makedirs(folder, exist_ok=True)
        
        # Configure app
        app.config.from_object(Config)

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
    # Add production-specific settings here

class TestingConfig(Config):
    TESTING = True
    # Add test-specific settings here

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}