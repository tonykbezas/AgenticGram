"""
Session Manager for AgenticGram.
Handles session persistence, working directories, and permission history.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict


logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents a user session."""
    telegram_id: int
    session_id: str
    work_dir: str
    created_at: datetime
    last_used: datetime
    message_count: int = 0
    
    def to_dict(self) -> dict:
        """Convert session to dictionary."""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        data['last_used'] = self.last_used.isoformat()
        return data


@dataclass
class PermissionRequest:
    """Represents a permission request."""
    request_id: str
    session_id: str
    action_type: str  # 'file_edit', 'command_exec', etc.
    details: dict
    requested_at: datetime
    approved: Optional[bool] = None
    responded_at: Optional[datetime] = None


class SessionManager:
    """Manages user sessions and permission history."""
    
    def __init__(self, db_path: str = ".sessions.db", work_dir_base: str = "./workspace"):
        """
        Initialize session manager.
        
        Args:
            db_path: Path to SQLite database
            work_dir_base: Base directory for session workspaces
        """
        self.db_path = db_path
        self.work_dir_base = Path(work_dir_base)
        self.work_dir_base.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize SQLite database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    telegram_id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    work_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0
                )
            """)
            
            # Permission history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS permissions (
                    request_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    details TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    approved INTEGER,
                    responded_at TEXT
                )
            """)
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    def create_session(self, telegram_id: int) -> Session:
        """
        Create a new session for a user.
        
        Args:
            telegram_id: Telegram user ID
            
        Returns:
            New Session object
        """
        session_id = f"session_{telegram_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        work_dir = self.work_dir_base / f"user_{telegram_id}" / session_id
        work_dir.mkdir(parents=True, exist_ok=True)
        
        now = datetime.now()
        session = Session(
            telegram_id=telegram_id,
            session_id=session_id,
            work_dir=str(work_dir),
            created_at=now,
            last_used=now
        )
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sessions 
                (telegram_id, session_id, work_dir, created_at, last_used, message_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                session.telegram_id,
                session.session_id,
                session.work_dir,
                session.created_at.isoformat(),
                session.last_used.isoformat(),
                session.message_count
            ))
            conn.commit()
        
        logger.info(f"Created new session {session_id} for user {telegram_id}")
        return session
    
    def set_work_directory(self, telegram_id: int, custom_path: str) -> Optional[Session]:
        """
        Set a custom work directory for a user's session.
        
        Args:
            telegram_id: Telegram user ID
            custom_path: Custom directory path to use as workspace
            
        Returns:
            Updated Session object if successful, None otherwise
        """
        # Validate the directory exists and is accessible
        custom_dir = Path(custom_path).resolve()
        if not custom_dir.exists():
            logger.error(f"Custom directory does not exist: {custom_path}")
            return None
        
        if not custom_dir.is_dir():
            logger.error(f"Path is not a directory: {custom_path}")
            return None
        
        # Get or create session
        session = self.get_session(telegram_id)
        if not session:
            session = self.create_session(telegram_id)
        
        # Create workspace subdirectory in custom path
        workspace = custom_dir / f"agenticgram_{telegram_id}"
        
        try:
            workspace.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            logger.error(f"Permission denied creating workspace in: {custom_path}")
            return None
        except Exception as e:
            logger.error(f"Error creating workspace directory: {e}")
            return None
        
        # Update session with new work directory
        session.work_dir = str(workspace)
        session.last_used = datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sessions 
                SET work_dir = ?, last_used = ?
                WHERE telegram_id = ?
            """, (
                session.work_dir,
                session.last_used.isoformat(),
                telegram_id
            ))
            conn.commit()
        
        logger.info(f"Set custom work directory for user {telegram_id}: {workspace}")
        return session
    
    def get_session(self, telegram_id: int) -> Optional[Session]:
        """
        Get existing session for a user.
        
        Args:
            telegram_id: Telegram user ID
            
        Returns:
            Session object if exists, None otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT telegram_id, session_id, work_dir, created_at, last_used, message_count
                FROM sessions WHERE telegram_id = ?
            """, (telegram_id,))
            
            row = cursor.fetchone()
            if row:
                return Session(
                    telegram_id=row[0],
                    session_id=row[1],
                    work_dir=row[2],
                    created_at=datetime.fromisoformat(row[3]),
                    last_used=datetime.fromisoformat(row[4]),
                    message_count=row[5]
                )
        
        return None
    
    def update_session(self, session: Session) -> None:
        """
        Update session in database.
        
        Args:
            session: Session object to update
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sessions 
                SET session_id = ?, work_dir = ?, last_used = ?, message_count = ?
                WHERE telegram_id = ?
            """, (
                session.session_id,
                session.work_dir,
                session.last_used.isoformat(),
                session.message_count,
                session.telegram_id
            ))
            conn.commit()
    
    def delete_session(self, telegram_id: int) -> bool:
        """
        Delete a user's session.
        
        Args:
            telegram_id: Telegram user ID
            
        Returns:
            True if session was deleted, False if not found
        """
        session = self.get_session(telegram_id)
        if not session:
            return False
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE telegram_id = ?", (telegram_id,))
            cursor.execute("DELETE FROM permissions WHERE session_id = ?", (session.session_id,))
            conn.commit()
        
        logger.info(f"Deleted session for user {telegram_id}")
        return True
    
    def log_permission_request(self, request: PermissionRequest) -> None:
        """
        Log a permission request to the database.
        
        Args:
            request: PermissionRequest object
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO permissions 
                (request_id, session_id, action_type, details, requested_at, approved, responded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                request.request_id,
                request.session_id,
                request.action_type,
                json.dumps(request.details),
                request.requested_at.isoformat(),
                request.approved,
                request.responded_at.isoformat() if request.responded_at else None
            ))
            conn.commit()
    
    def update_permission_response(self, request_id: str, approved: bool) -> None:
        """
        Update permission request with user response.
        
        Args:
            request_id: Permission request ID
            approved: Whether the request was approved
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE permissions 
                SET approved = ?, responded_at = ?
                WHERE request_id = ?
            """, (approved, datetime.now().isoformat(), request_id))
            conn.commit()
    
    def get_permission_history(self, session_id: str, limit: int = 50) -> List[PermissionRequest]:
        """
        Get permission history for a session.
        
        Args:
            session_id: Session ID
            limit: Maximum number of records to return
            
        Returns:
            List of PermissionRequest objects
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT request_id, session_id, action_type, details, requested_at, approved, responded_at
                FROM permissions 
                WHERE session_id = ?
                ORDER BY requested_at DESC
                LIMIT ?
            """, (session_id, limit))
            
            history = []
            for row in cursor.fetchall():
                history.append(PermissionRequest(
                    request_id=row[0],
                    session_id=row[1],
                    action_type=row[2],
                    details=json.loads(row[3]),
                    requested_at=datetime.fromisoformat(row[4]),
                    approved=bool(row[5]) if row[5] is not None else None,
                    responded_at=datetime.fromisoformat(row[6]) if row[6] else None
                ))
            
            return history
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up sessions older than specified age.
        
        Args:
            max_age_hours: Maximum age in hours
            
        Returns:
            Number of sessions cleaned up
        """
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT telegram_id FROM sessions 
                WHERE last_used < ?
            """, (cutoff_time.isoformat(),))
            
            old_sessions = cursor.fetchall()
            count = len(old_sessions)
            
            for (telegram_id,) in old_sessions:
                self.delete_session(telegram_id)
        
        logger.info(f"Cleaned up {count} old sessions")
        return count
