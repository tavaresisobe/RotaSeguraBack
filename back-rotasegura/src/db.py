from pymongo import MongoClient
from src.settings import MONGO_URI, DB_NAME

def get_mongo_connection():
    if not MONGO_URI:
        raise ValueError("MONGO_URI não encontrada. Verifique o arquivo .env")
    client = MongoClient(MONGO_URI)
    return client[DB_NAME]
