import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'una_clave_muy_segura_12345')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///historia_clinica.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
