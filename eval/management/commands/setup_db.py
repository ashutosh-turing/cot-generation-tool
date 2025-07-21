import os
from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Sets up required database tables'

    def handle(self, *args, **options):
        cursor = connection.cursor()
        
        # Create django_site table if it doesn't exist
        self.stdout.write('Creating django_site table...')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS django_site (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain VARCHAR(100) NOT NULL,
            name VARCHAR(50) NOT NULL
        )
        ''')
        
        # Insert default site if needed
        cursor.execute('SELECT COUNT(*) FROM django_site')
        count = cursor.fetchone()[0]
        if count == 0:
            self.stdout.write('Adding default site...')
            cursor.execute('''
            INSERT INTO django_site (id, domain, name)
            VALUES (1, 'example.com', 'example.com')
            ''')
        
        # Create django_session table if it doesn't exist
        self.stdout.write('Creating django_session table...')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS django_session (
            session_key VARCHAR(40) NOT NULL PRIMARY KEY,
            session_data TEXT NOT NULL,
            expire_date DATETIME NOT NULL
        )
        ''')
        
        # Create eval_streamandsubject table if it doesn't exist
        self.stdout.write('Creating eval_streamandsubject table...')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS eval_streamandsubject (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create eval_systemmessage table if it doesn't exist
        self.stdout.write('Creating eval_systemmessage table...')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS eval_systemmessage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT 0,
            category_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES eval_streamandsubject(id)
        )
        ''')
        
        self.stdout.write(self.style.SUCCESS('Database tables created successfully'))
