import os
from pdf2image import convert_from_path
from PIL import Image
import pytesseract
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import json
from typing import List, Dict, Tuple

# Constants
OUTPUT_TEXT_FOLDER = 'output_text'
IMAGE_FOLDER = 'images'

# Create necessary folders
for folder in [OUTPUT_TEXT_FOLDER, IMAGE_FOLDER]:
    os.makedirs(folder, exist_ok=True)

def convert_pdf_to_images(pdf_path: str, session_id: str, username: str) -> List[str]:
    """Convert PDF to images and save them in user's folder."""
    user_image_folder = os.path.join(IMAGE_FOLDER, username)
    os.makedirs(user_image_folder, exist_ok=True)

    images = convert_from_path(pdf_path)
    image_paths = []

    for i, image in enumerate(images):
        image_filename = f"{session_id}_page_{i + 1}.png"
        image_path = os.path.join(user_image_folder, image_filename)
        image.save(image_path, "PNG")
        image_paths.append(image_path)

    return image_paths

def extract_text_from_images(image_paths: List[str]) -> str:
    """Extract text from images using OCR."""
    extracted_text = ""
    for image_path in image_paths:
        try:
            text = pytesseract.image_to_string(Image.open(image_path), lang="eng")
            extracted_text += f"\n--- Text from {os.path.basename(image_path)} ---\n{text}\n"
        except Exception as e:
            print(f"Error processing image {image_path}: {str(e)}")
    return extracted_text

def process_pdf_to_text(pdf_path: str, session_id: str, username: str) -> Tuple[List[str], str]:
    """Process PDF file to extract text using OCR."""
    image_paths = convert_pdf_to_images(pdf_path, session_id, username)
    extracted_text = extract_text_from_images(image_paths)
    
    ocr_text_path = os.path.join(OUTPUT_TEXT_FOLDER, f"{session_id}_ocr.txt")
    with open(ocr_text_path, "w", encoding="utf-8") as text_file:
        text_file.write(extracted_text)
    
    return image_paths, ocr_text_path

def extract_key_value_pairs(cosmos_container, username: str) -> Dict[str, str]:
    """Extract text data from Cosmos DB for a specific user."""
    query = f"SELECT * FROM c WHERE c.partitionKey = '{username}'"
    items = list(cosmos_container.query_items(query=query, enable_cross_partition_query=True))
    return {item['id']: item['text'] for item in items}

def perform_word_embedding(texts: Dict[str, str]) -> Dict[str, np.ndarray]:
    """Generate embeddings for text using sentence transformers."""
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    embeddings = {}
    for key, text in texts.items():
        try:
            embedding = model.encode(text, convert_to_tensor=False)
            embeddings[key] = embedding
        except Exception as e:
            print(f"Error generating embedding for {key}: {str(e)}")
    return embeddings

def search_similar_documents(embeddings: Dict[str, np.ndarray], top_k: int = 5) -> Dict[str, List[str]]:
    """Search for similar documents using FAISS."""
    if not embeddings:
        return {}
        
    keys = list(embeddings.keys())
    values = np.vstack(list(embeddings.values()))
    
    # Initialize FAISS index
    dimension = values.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(values.astype('float32'))
    
    # Search for similar documents
    D, I = index.search(values.astype('float32'), min(top_k, len(keys)))
    return {keys[i]: [keys[j] for j in I[i]] for i in range(len(keys))}