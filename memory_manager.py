import os
import sqlite3
import urllib.parse
import requests
import json
import re
import uuid
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("jarvis")

# Paths and Configs
USER_HOME = os.path.expanduser("~")
JARVIS_DIR = os.path.join(USER_HOME, ".jarvis")
DB_PATH = os.path.join(JARVIS_DIR, "memory.db")
CHROMA_DIR = os.path.join(JARVIS_DIR, "chroma_db")

def init_db():
    """
    Initializes the SQLite database schema if memory.db does not exist.
    """
    os.makedirs(JARVIS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Conversations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        user_input TEXT,
        jarvis_response TEXT,
        session_id TEXT
    )
    """)
    
    # User facts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE,
        value TEXT,
        confidence REAL,
        last_updated TEXT,
        source TEXT
    )
    """)
    
    # Habits table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS habits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern TEXT UNIQUE,
        count INTEGER,
        last_seen TEXT,
        first_seen TEXT
    )
    """)
    
    # Reminders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        remind_at TEXT,
        completed INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)
    
    conn.commit()
    conn.close()
    logger.info("SQLite Structured Memory database initialized.")

class MemoryManager:
    """
    Manages structured (SQLite) and semantic (ChromaDB) memory for J.A.R.V.I.S.
    """
    def __init__(self, ollama_url="http://localhost:11434/api/generate", embed_model="nomic-embed-text"):
        init_db()
        
        # Resolve embeddings endpoint
        parsed_url = urllib.parse.urlparse(ollama_url)
        self.embedding_url = f"{parsed_url.scheme}://{parsed_url.netloc}/api/embeddings"
        self.embed_model = embed_model
        
        # Initialize ChromaDB persistent client
        os.makedirs(CHROMA_DIR, exist_ok=True)
        try:
            import chromadb
            self.chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
            self.collection = self.chroma_client.get_or_create_collection(name="jarvis_memory")
            logger.info("ChromaDB Semantic Memory initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            self.collection = None

    def _get_embedding(self, text):
        """
        Calls Ollama embeddings endpoint to generate vector for text.
        """
        try:
            # Quick check if Ollama is running
            parsed_url = urllib.parse.urlparse(self.embedding_url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            requests.get(f"{base_url}/api/tags", timeout=2)
            
            payload = {
                "model": self.embed_model,
                "prompt": text
            }
            logger.info(f"Generating embedding via Ollama for: '{text[:20]}...'")
            r = requests.post(self.embedding_url, json=payload, timeout=5)
            r.raise_for_status()
            return r.json().get("embedding")
        except Exception as e:
            logger.warning(f"Failed to generate embedding (Ollama offline/model missing): {e}")
            return None

    def save_conversation(self, user_input, jarvis_response, session_id):
        """
        Saves conversation turn to SQLite + generates and stores embedding in ChromaDB.
        """
        # 1. Save to SQLite
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        try:
            cursor.execute(
                "INSERT INTO conversations (timestamp, user_input, jarvis_response, session_id) VALUES (?, ?, ?, ?)",
                (now_str, user_input, jarvis_response, session_id)
            )
            conn.commit()
            logger.info("Conversation turn saved to SQLite.")
        except Exception as e:
            logger.error(f"Error saving conversation to SQLite: {e}")
        finally:
            conn.close()
            
        # 2. Track Habits from input
        self.track_habits(user_input)
        
        # 3. Save to ChromaDB
        if self.collection:
            # We generate embedding of the user's query
            embedding = self._get_embedding(user_input)
            if embedding:
                try:
                    turn_id = str(uuid.uuid4())
                    document = f"User asked: {user_input}\nJarvis replied: {jarvis_response}"
                    self.collection.add(
                        ids=[turn_id],
                        embeddings=[embedding],
                        documents=[document],
                        metadatas=[{"timestamp": now_str, "session_id": session_id}]
                    )
                    logger.info("Conversation turn added to ChromaDB.")
                except Exception as e:
                    logger.error(f"Error adding to ChromaDB collection: {e}")

    def extract_and_save_facts(self, text):
        """
        Scans user speech for personal facts using regex and saves to SQLite.
        """
        text_lower = text.lower().strip()
        
        # 1. Name matches
        name_match = re.search(r"\bmy name is\s+([a-z\s]+)", text_lower)
        if not name_match:
            name_match = re.search(r"\bi'm\s+([a-z\s]+)", text_lower)
            # Filter verbs/common adjectives
            if name_match:
                words = name_match.group(1).split()
                if len(words) > 0 and words[0] in ('going', 'running', 'doing', 'working', 'tired', 'sorry', 'sure', 'not', 'here', 'ready'):
                    name_match = None
        if name_match:
            name = name_match.group(1).strip().title()
            name = name.split(" And ")[0].split(" But ")[0].split(".")[0].strip()
            if name and len(name.split()) <= 3:
                self.save_user_fact("user_name", name, confidence=0.9, source="conversational_extraction")
                
        # 2. City matches
        city_match = re.search(r"\bi live in\s+([a-z\s]+)", text_lower)
        if not city_match:
            city_match = re.search(r"\bi'm from\s+([a-z\s]+)", text_lower)
        if city_match:
            city = city_match.group(1).strip().title()
            city = city.split(".")[0].strip()
            if city and len(city.split()) <= 3:
                self.save_user_fact("user_city", city, confidence=0.85, source="conversational_extraction")
                
        # 3. Job matches
        job_match = re.search(r"\bi work as\s+(?:a\s+|an\s+)?([a-z\s]+)", text_lower)
        if not job_match:
            job_match = re.search(r"\bi am\s+(?:a\s+|an\s+)?(software engineer|developer|coder|programmer|designer|manager|student|doctor|teacher|engineer|writer|accountant)\b", text_lower)
        if job_match:
            job = job_match.group(1).strip().title()
            job = job.split(".")[0].strip()
            if job:
                self.save_user_fact("user_job", job, confidence=0.8, source="conversational_extraction")
                
        # 4. Preferences matches
        pref_match = re.search(r"\bi like\s+([a-z0-9\s]+)", text_lower)
        if pref_match:
            pref = pref_match.group(1).strip()
            pref = pref.split(".")[0].strip()
            if pref and len(pref) < 30:
                self.save_user_fact(f"user_preference_{pref.replace(' ', '_')}", "True", confidence=0.7, source="conversational_extraction")

    def save_user_fact(self, key, value, confidence=0.8, source="extraction"):
        """
        Saves or updates user fact in user_facts SQLite table.
        """
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        try:
            cursor.execute("""
            INSERT INTO user_facts (key, value, confidence, last_updated, source)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                confidence=excluded.confidence,
                last_updated=excluded.last_updated,
                source=excluded.source
            """, (key, value, confidence, now_str, source))
            conn.commit()
            logger.info(f"User fact saved: {key} -> {value}")
        except Exception as e:
            logger.error(f"Error saving user fact to SQLite: {e}")
        finally:
            conn.close()

    def get_user_facts(self):
        """
        Queries and returns a dict of all known facts about the user.
        """
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        facts = {}
        try:
            cursor.execute("SELECT key, value FROM user_facts")
            for row in cursor.fetchall():
                facts[row[0]] = row[1]
        except Exception as e:
            logger.error(f"Error querying user facts: {e}")
        finally:
            conn.close()
        return facts

    def track_habits(self, user_input):
        """
        Scans queries to log habits (such as asking for weather).
        """
        text_lower = user_input.lower().strip()
        if "weather" in text_lower:
            now = datetime.now()
            if 5 <= now.hour < 12:
                self.increment_habit("asks weather every morning")
            else:
                self.increment_habit("asks weather")
        if "screenshot" in text_lower:
            self.increment_habit("takes screenshot")
        if "time" in text_lower:
            self.increment_habit("checks time")
        if "date" in text_lower:
            self.increment_habit("checks date")

    def increment_habit(self, pattern):
        """
        Increments the counter or creates the habit tracker in SQLite habits table.
        """
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        try:
            cursor.execute("SELECT count, first_seen FROM habits WHERE pattern=?", (pattern,))
            row = cursor.fetchone()
            if row:
                count = row[0] + 1
                cursor.execute(
                    "UPDATE habits SET count=?, last_seen=? WHERE pattern=?",
                    (count, now_str, pattern)
                )
            else:
                cursor.execute(
                    "INSERT INTO habits (pattern, count, last_seen, first_seen) VALUES (?, 1, ?, ?)",
                    (pattern, now_str, now_str)
                )
            conn.commit()
            logger.debug(f"Habit tracked: {pattern}")
        except Exception as e:
            logger.error(f"Error incrementing habit: {e}")
        finally:
            conn.close()

    def add_reminder(self, text, minutes):
        """
        Saves a scheduled reminder to SQLite reminders table.
        Called by skills.py when set_reminder triggers.
        """
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        created_at = datetime.now().isoformat()
        remind_at = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        try:
            cursor.execute(
                "INSERT INTO reminders (text, remind_at, completed, created_at) VALUES (?, ?, ?, ?)",
                (text, remind_at, 0, created_at)
            )
            conn.commit()
            logger.info(f"Structured memory reminder logged: '{text}' at {remind_at}")
        except Exception as e:
            logger.error(f"Error logging reminder to SQLite: {e}")
        finally:
            conn.close()

    def recall_relevant(self, query, n=3):
        """
        Queries ChromaDB collection for the top N most similar past dialogue turns.
        """
        if not self.collection:
            return []
            
        embedding = self._get_embedding(query)
        if not embedding:
            return []
            
        try:
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=n
            )
            documents = results.get("documents", [[]])[0]
            return [doc for doc in documents if doc]
        except Exception as e:
            logger.error(f"Error querying ChromaDB collection: {e}")
            return []

    def build_memory_context(self, current_query):
        """
        Gathers facts and semantic recollections, returns formatted context string for prompt.
        """
        # Facts
        facts = self.get_user_facts()
        facts_items = []
        for k, v in facts.items():
            clean_k = k.replace("user_", "")
            facts_items.append(f"{clean_k}={v}")
        facts_str = ", ".join(facts_items) if facts_items else "None"
        
        # Semantic recollections
        recollections = self.recall_relevant(current_query, n=3)
        recoll_str = ""
        for doc in recollections:
            recoll_str += f"\n- {doc}"
        if not recoll_str:
            recoll_str = "\n- No previous matching exchanges."
            
        context = (
            f"Known facts about the user: {facts_str}\n"
            f"Relevant past conversations:{recoll_str}"
        )
        return context

    def morning_briefing(self):
        """
        Generates morning briefing: weather, reminders, last dialogue summary.
        """
        # 1. Fetch weather via skills module
        weather = "weather data unavailable"
        try:
            from skills import get_weather
            weather = get_weather("auto")
        except Exception as e:
            logger.error(f"Failed to fetch weather for morning briefing: {e}")
            
        # 2. Count active reminders for today
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        today_str = datetime.now().strftime("%Y-%m-%d")
        reminders_count = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM reminders WHERE completed=0 AND remind_at LIKE ?", (f"{today_str}%",))
            reminders_count = cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error querying reminders count for briefing: {e}")
            
        # 3. Retrieve last conversation details
        last_exchange_str = "No recent conversations logged."
        try:
            cursor.execute("SELECT timestamp, user_input, jarvis_response FROM conversations ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                last_time = datetime.fromisoformat(row[0])
                diff = datetime.now() - last_time
                
                # Format time ago
                if diff.days > 0:
                    time_ago = f"{diff.days} day(s) ago"
                elif diff.seconds // 3600 > 0:
                    time_ago = f"{diff.seconds // 3600} hour(s) ago"
                else:
                    time_ago = f"{diff.seconds // 60} minute(s) ago"
                    
                topic = row[1][:35] + ("..." if len(row[1]) > 35 else "")
                last_exchange_str = f"Last time we spoke was {time_ago} about '{topic}'."
        except Exception as e:
            logger.error(f"Error querying last turn for briefing: {e}")
        finally:
            conn.close()
            
        briefing = (
            f"Good morning sir. {weather} You have {reminders_count} reminders scheduled for today. "
            f"{last_exchange_str}"
        )
        return briefing

def test_memory():
    """
    Test suite to verify SQLite and ChromaDB memory features.
    """
    print("--- Testing structured memory (SQLite) ---")
    mgr = MemoryManager()
    mgr.save_user_fact("user_name", "RahulTest", confidence=1.0, source="test")
    mgr.save_user_fact("user_city", "BhopalTest", confidence=1.0, source="test")
    
    facts = mgr.get_user_facts()
    print("Facts returned:", facts)
    assert facts.get("user_name") == "RahulTest"
    
    print("\n--- Testing fact regex extraction ---")
    mgr.extract_and_save_facts("My name is Rahul")
    mgr.extract_and_save_facts("I live in Bhopal")
    mgr.extract_and_save_facts("I work as a software engineer")
    mgr.extract_and_save_facts("I like black coffee")
    
    updated_facts = mgr.get_user_facts()
    print("Updated facts:", updated_facts)
    
    print("\n--- Testing save conversation + ChromaDB ---")
    mgr.save_conversation("What is python coding?", "Python is a popular programming language.", "test-session-123")
    
    print("\n--- Testing memory context building ---")
    ctx = mgr.build_memory_context("python coding")
    print("Generated Context:\n", ctx)
    
    print("\n--- Testing morning briefing ---")
    brief = mgr.morning_briefing()
    print("Generated Briefing:\n", brief)
    print("Memory verification completed successfully!")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_memory()
