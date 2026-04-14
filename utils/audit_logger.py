"""
Audit Logger for Telegram Commands

Provides tamper-evident logging for all Telegram command operations.
Logs are stored in JSONL format with hash chaining for integrity verification.

Reference: Evaluation report docs/reports/TELEGRAM_SYSTEM_EVALUATION_REPORT.md
"""

import json
import hashlib
import logging
import threading
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from enum import Enum


class AuditEventType(str, Enum):
    """Types of audit events."""
    # Command events
    COMMAND_RECEIVED = "command_received"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_FAILED = "command_failed"

    # Authentication events
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILED = "auth_failed"
    AUTH_2FA_REQUESTED = "auth_2fa_requested"
    AUTH_2FA_SUCCESS = "auth_2fa_success"
    AUTH_2FA_FAILED = "auth_2fa_failed"

    # Trading events
    PAUSE_REQUESTED = "pause_requested"
    RESUME_REQUESTED = "resume_requested"
    CLOSE_REQUESTED = "close_requested"
    CLOSE_CONFIRMED = "close_confirmed"
    CLOSE_CANCELLED = "close_cancelled"

    # System events
    BOT_STARTED = "bot_started"
    BOT_STOPPED = "bot_stopped"
    ERROR = "error"


class AuditLogger:
    """
    Tamper-evident audit logger with hash chaining.

    Features:
    - JSONL format for easy parsing
    - Hash chaining for integrity verification
    - Thread-safe operations
    - Automatic log rotation (by date)
    - Query/export capabilities

    Log Entry Format:
    {
        "timestamp": "2026-02-01T12:00:00.000Z",
        "event_type": "command_executed",
        "user_id": "123456789",
        "command": "/close",
        "args": {},
        "result": "success",
        "details": {...},
        "prev_hash": "abc123...",
        "hash": "def456..."
    }
    """

    def __init__(
        self,
        log_dir: str = "logs/audit",
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize audit logger.

        Parameters
        ----------
        log_dir : str
            Directory to store audit logs
        logger : logging.Logger
            Logger for operational messages
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger(__name__)

        self._lock = threading.Lock()
        self._prev_hash = "0" * 64  # Genesis hash

        # Load previous hash from last log entry
        self._load_prev_hash()

        self.logger.info(f"📝 Audit logger initialized: {self.log_dir}")

    def _get_log_file(self, date: Optional[datetime] = None) -> Path:
        """Get log file path for a specific date."""
        if date is None:
            date = datetime.utcnow()
        filename = f"audit_{date.strftime('%Y%m%d')}.jsonl"
        return self.log_dir / filename

    def _load_prev_hash(self):
        """Load previous hash from the last log entry."""
        try:
            # Find the most recent log file
            log_files = sorted(self.log_dir.glob("audit_*.jsonl"), reverse=True)
            if not log_files:
                return

            # Read the last line
            with open(log_files[0], 'r') as f:
                lines = f.readlines()
                if lines:
                    last_entry = json.loads(lines[-1].strip())
                    self._prev_hash = last_entry.get('hash', self._prev_hash)
                    self.logger.debug(f"Loaded prev_hash: {self._prev_hash[:16]}...")

        except Exception as e:
            self.logger.warning(f"⚠️ Could not load previous hash: {e}")

    def _compute_hash(self, entry: Dict[str, Any]) -> str:
        """Compute SHA-256 hash for an entry."""
        # Create deterministic JSON string (sorted keys)
        entry_str = json.dumps(entry, sort_keys=True, default=str)
        return hashlib.sha256(entry_str.encode()).hexdigest()

    def log(
        self,
        event_type: AuditEventType,
        user_id: str,
        command: Optional[str] = None,
        args: Optional[Dict] = None,
        result: str = "success",
        details: Optional[Dict] = None,
    ) -> bool:
        """
        Log an audit event.

        Parameters
        ----------
        event_type : AuditEventType
            Type of event
        user_id : str
            Telegram user/chat ID
        command : str, optional
            Command that was executed
        args : dict, optional
            Command arguments
        result : str
            Result of the operation (success/failed/cancelled)
        details : dict, optional
            Additional details

        Returns
        -------
        bool
            True if logged successfully
        """
        with self._lock:
            try:
                now = datetime.utcnow()

                # Build entry (without hash first)
                entry = {
                    "timestamp": now.isoformat() + "Z",
                    "event_type": event_type.value,
                    "user_id": str(user_id),
                    "command": command,
                    "args": args or {},
                    "result": result,
                    "details": details or {},
                    "prev_hash": self._prev_hash,
                }

                # Compute hash
                entry["hash"] = self._compute_hash(entry)

                # Write to log file
                log_file = self._get_log_file(now)
                with open(log_file, 'a') as f:
                    f.write(json.dumps(entry) + '\n')

                # Update prev_hash
                self._prev_hash = entry["hash"]

                self.logger.debug(
                    f"📝 Audit: {event_type.value} user={user_id} cmd={command} result={result}"
                )
                return True

            except Exception as e:
                self.logger.error(f"❌ Failed to write audit log: {e}")
                return False

    def log_command(
        self,
        user_id: str,
        command: str,
        args: Optional[Dict] = None,
        result: str = "success",
        error_message: Optional[str] = None,
    ) -> bool:
        """Convenience method to log a command execution."""
        event_type = (
            AuditEventType.COMMAND_EXECUTED if result == "success"
            else AuditEventType.COMMAND_FAILED
        )
        details = {}
        if error_message:
            details["error"] = error_message

        return self.log(
            event_type=event_type,
            user_id=user_id,
            command=command,
            args=args,
            result=result,
            details=details,
        )

    def log_auth(
        self,
        user_id: str,
        success: bool,
        method: str = "chat_id",
        reason: Optional[str] = None,
    ) -> bool:
        """Log an authentication attempt."""
        event_type = AuditEventType.AUTH_SUCCESS if success else AuditEventType.AUTH_FAILED
        return self.log(
            event_type=event_type,
            user_id=user_id,
            result="success" if success else "failed",
            details={"method": method, "reason": reason},
        )

    def log_2fa(
        self,
        user_id: str,
        event: str,  # "requested", "success", "failed"
        command: str,
    ) -> bool:
        """Log 2FA events."""
        event_map = {
            "requested": AuditEventType.AUTH_2FA_REQUESTED,
            "success": AuditEventType.AUTH_2FA_SUCCESS,
            "failed": AuditEventType.AUTH_2FA_FAILED,
        }
        return self.log(
            event_type=event_map.get(event, AuditEventType.AUTH_2FA_REQUESTED),
            user_id=user_id,
            command=command,
            result=event,
        )

    def log_trading_action(
        self,
        user_id: str,
        action: str,  # "pause", "resume", "close"
        result: str = "success",
        details: Optional[Dict] = None,
    ) -> bool:
        """Log trading control actions."""
        action_map = {
            "pause": AuditEventType.PAUSE_REQUESTED,
            "resume": AuditEventType.RESUME_REQUESTED,
            "close_request": AuditEventType.CLOSE_REQUESTED,
            "close_confirm": AuditEventType.CLOSE_CONFIRMED,
            "close_cancel": AuditEventType.CLOSE_CANCELLED,
        }
        return self.log(
            event_type=action_map.get(action, AuditEventType.COMMAND_EXECUTED),
            user_id=user_id,
            command=f"/{action.replace('_request', '').replace('_confirm', '').replace('_cancel', '')}",
            result=result,
            details=details,
        )

    def verify_integrity(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Verify the integrity of the audit log using hash chain.

        Parameters
        ----------
        date : datetime, optional
            Date to verify (defaults to today)

        Returns
        -------
        dict
            Verification result with status and details
        """
        log_file = self._get_log_file(date)
        if not log_file.exists():
            return {"status": "no_file", "message": f"No log file: {log_file}"}

        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()

            if not lines:
                return {"status": "empty", "message": "Log file is empty"}

            prev_hash = None
            errors = []

            for i, line in enumerate(lines):
                try:
                    entry = json.loads(line.strip())

                    # Check prev_hash chain
                    if prev_hash is not None and entry.get("prev_hash") != prev_hash:
                        errors.append(f"Line {i+1}: prev_hash mismatch")

                    # Verify entry hash
                    stored_hash = entry.pop("hash", None)
                    computed_hash = self._compute_hash(entry)
                    if stored_hash != computed_hash:
                        errors.append(f"Line {i+1}: hash mismatch")

                    prev_hash = stored_hash

                except json.JSONDecodeError:
                    errors.append(f"Line {i+1}: invalid JSON")

            if errors:
                return {
                    "status": "failed",
                    "message": f"Integrity check failed: {len(errors)} errors",
                    "errors": errors,
                }

            return {
                "status": "ok",
                "message": f"Verified {len(lines)} entries",
                "entries": len(lines),
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def query(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        user_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        command: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query audit logs with filters.

        Parameters
        ----------
        start_date : datetime, optional
            Start of date range
        end_date : datetime, optional
            End of date range
        user_id : str, optional
            Filter by user ID
        event_type : AuditEventType, optional
            Filter by event type
        command : str, optional
            Filter by command
        limit : int
            Maximum entries to return

        Returns
        -------
        list
            Matching log entries
        """
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)

        results = []

        # Find relevant log files
        current = start_date
        while current <= end_date and len(results) < limit:
            log_file = self._get_log_file(current)
            if log_file.exists():
                with open(log_file, 'r') as f:
                    for line in f:
                        if len(results) >= limit:
                            break

                        try:
                            entry = json.loads(line.strip())

                            # Apply filters
                            if user_id and entry.get("user_id") != user_id:
                                continue
                            if event_type and entry.get("event_type") != event_type.value:
                                continue
                            if command and entry.get("command") != command:
                                continue

                            results.append(entry)

                        except json.JSONDecodeError:
                            continue

            current = current + timedelta(days=1)

        return results

    def export_csv(
        self,
        output_file: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> int:
        """
        Export audit logs to CSV format.

        Parameters
        ----------
        output_file : str
            Output CSV file path
        start_date : datetime, optional
            Start of date range
        end_date : datetime, optional
            End of date range

        Returns
        -------
        int
            Number of entries exported
        """
        import csv

        entries = self.query(start_date=start_date, end_date=end_date, limit=100000)

        if not entries:
            return 0

        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "timestamp", "event_type", "user_id", "command", "result"
            ])
            writer.writeheader()
            for entry in entries:
                writer.writerow({
                    "timestamp": entry.get("timestamp"),
                    "event_type": entry.get("event_type"),
                    "user_id": entry.get("user_id"),
                    "command": entry.get("command"),
                    "result": entry.get("result"),
                })

        return len(entries)


# Global instance for convenience
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(log_dir: str = "logs/audit") -> AuditLogger:
    """Get or create the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(log_dir=log_dir)
    return _audit_logger
