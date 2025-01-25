from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from azure.cosmos import CosmosClient
import os
import logging
from datetime import datetime
import pyodbc
from operations import process_pdf_to_text, extract_key_value_pairs, perform_word_embedding, search_similar_documents
import json
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback_secret_key')

# Configure folders
UPLOAD_FOLDER = 'uploads'
IMAGE_FOLDER = 'images'
OUTPUT_TEXT_FOLDER = 'output_text'

for folder in [UPLOAD_FOLDER, IMAGE_FOLDER, OUTPUT_TEXT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Azure Cosmos DB configuration
COSMOS_ENDPOINT = os.environ.get('COSMOS_ENDPOINT')
COSMOS_KEY = os.environ.get('COSMOS_KEY')
COSMOS_DB_NAME = os.environ.get('COSMOS_DB_NAME')
COSMOS_CONTAINER_NAME = os.environ.get('COSMOS_CONTAINER_NAME')

# Azure SQL connection
AZURE_SQL_CONN_STR = os.environ.get('AZURE_SQL_CONN_STR')

# Configure Google AI
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-pro')
else:
    logger.error("Google API Key not found in environment variables")

def get_db_connection():
    """Get SQL database connection."""
    try:
        if not AZURE_SQL_CONN_STR:
            raise ValueError("Azure SQL connection string is not set")
        conn = pyodbc.connect(AZURE_SQL_CONN_STR)
        logger.debug("Database connection successful")
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        raise

def initialize_database():
    """Initialize the database and create tables if they don't exist."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create Users table if it doesn't exist
        cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Users' AND xtype='U')
        CREATE TABLE Users (
            UserID INT IDENTITY(1,1) PRIMARY KEY,
            Username NVARCHAR(50) UNIQUE NOT NULL,
            PasswordHash NVARCHAR(255) NOT NULL,
            CreatedAt DATETIME DEFAULT GETDATE()
        )
        """)
        conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

# Initialize database on startup
initialize_database()

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if not username or not password:
            flash('Username and password are required')
            return render_template('register.html')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if user exists
            cursor.execute("SELECT COUNT(*) FROM Users WHERE Username = ?", (username,))
            if cursor.fetchone()[0] > 0:
                flash('Username already exists')
                return render_template('register.html')

            # Create new user
            hashed_password = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO Users (Username, PasswordHash, CreatedAt) VALUES (?, ?, ?)",
                (username, hashed_password, datetime.utcnow())
            )
            conn.commit()
            logger.info(f"User {username} registered successfully")
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except Exception as e:
            logger.error(f"Registration error for user {username}: {str(e)}")
            flash('Registration failed. Please try again.')
            return render_template('register.html')
        finally:
            if 'conn' in locals():
                conn.close()

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if not username or not password:
            flash('Username and password are required')
            return render_template('login.html')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT PasswordHash FROM Users WHERE Username = ?", (username,))
            result = cursor.fetchone()
            
            if result and check_password_hash(result[0], password):
                session['username'] = username
                logger.info(f"User {username} logged in successfully")
                flash('Login successful!')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password')
                return render_template('login.html')
        except Exception as e:
            logger.error(f"Login error for user {username}: {str(e)}")
            flash('Login failed. Please try again.')
            return render_template('login.html')
        finally:
            if 'conn' in locals():
                conn.close()

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        flash('Please login first')
        return redirect(url_for('login'))
    
    try:
        # Get user's documents from Cosmos DB
        documents = extract_key_value_pairs(cosmos_container, session['username'])
        return render_template('dashboard.html', documents=documents)
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        flash('Error loading dashboard')
        return render_template('dashboard.html', documents={})

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        if file and file.filename.endswith('.pdf'):
            filename = secure_filename(file.filename)
            session_id = f"{session['username']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Process PDF
            image_paths, text_path = process_pdf_to_text(file_path, session_id, session['username'])
            
            # Store in Cosmos DB
            with open(text_path, 'r', encoding='utf-8') as f:
                text_content = f.read()
            
            cosmos_container.create_item(
                body={
                    'id': session_id,
                    'partitionKey': session['username'],
                    'filename': filename,
                    'text': text_content,
                    'uploadedAt': datetime.utcnow().isoformat()
                }
            )
            
            return jsonify({
                'success': True,
                'message': 'File processed successfully',
                'session_id': session_id
            })
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/search', methods=['POST'])
def search():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        documents = extract_key_value_pairs(cosmos_container, session['username'])
        if not documents:
            return jsonify({'message': 'No documents found'}), 404
        
        embeddings = perform_word_embedding(documents)
        similar_docs = search_similar_documents(embeddings)
        
        return jsonify({'results': similar_docs})
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/chatbot', methods=['POST'])
def chatbot():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        data = request.get_json()
        user_input = data.get('user_input', '')
        
        # Get context from user's documents
        documents = extract_key_value_pairs(cosmos_container, session['username'])
        context = "\n".join(documents.values()) if documents else ""
        
        # Generate response using Google AI
        prompt = f"""Context: {context[:1000]}...
        
        User Question: {user_input}
        
        Please provide a helpful response based on the context above."""
        
        response = model.generate_content(prompt)
        return jsonify({'response': response.text})
    except Exception as e:
        logger.error(f"Chatbot error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    username = session.pop('username', None)
    if username:
        logger.info(f"User {username} logged out")
    flash('You have been logged out')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
