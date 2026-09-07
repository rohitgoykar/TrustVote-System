import hashlib
import json
import sqlite3
from datetime import datetime

class Block:
    """
    Cryptographic Block representing an immutable vote or system event.
    """
    def __init__(self, index, timestamp, voter_id_hash, election, booth_code, booth_id, booth_officer, region, previous_hash, nonce=0, block_hash=None):
        self.index = index
        self.timestamp = timestamp
        self.voter_id_hash = voter_id_hash
        self.election = election
        self.booth_code = booth_code
        self.booth_id = booth_id
        self.booth_officer = booth_officer
        self.region = region
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = block_hash or self.calculate_hash()

    def calculate_hash(self):
        """
        Calculates SHA-256 hash over all block data fields.
        """
        block_string = (
            f"{self.index}|{self.timestamp}|{self.voter_id_hash}|{self.election}|"
            f"{self.booth_code}|{self.booth_id}|{self.booth_officer}|{self.region}|"
            f"{self.previous_hash}|{self.nonce}"
        )
        return hashlib.sha256(block_string.encode('utf-8')).hexdigest()

    def to_dict(self):
        return {
            "block_index": self.index,
            "timestamp": self.timestamp,
            "voter_id_hash": self.voter_id_hash,
            "election": self.election,
            "booth_code": self.booth_code,
            "booth_id": self.booth_id,
            "booth_officer": self.booth_officer,
            "region": self.region,
            "previous_hash": self.previous_hash,
            "block_hash": self.hash,
            "nonce": self.nonce
        }


class Blockchain:
    """
    Manages the persistent blockchain ledger stored in the database.
    """
    GENESIS_PREV_HASH = "0" * 64
    GENESIS_SEED = "SEC_MAHARASHTRA_GENESIS_ROOT_TRUSTVOTE_2026"

    @staticmethod
    def hash_voter_id(v_id: str) -> str:
        """
        Computes SHA-256 of Voter ID for zero-knowledge privacy.
        """
        salt = "SEC_MAHA_VOTER_SALT_v1"
        return hashlib.sha256(f"{v_id}:{salt}".encode('utf-8')).hexdigest()

    @classmethod
    def get_latest_block(cls, conn):
        """
        Retrieves the latest block from the database ledger.
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT block_index, timestamp, voter_id_hash, election, booth_code, 
                   booth_id, booth_officer, region, previous_hash, nonce, block_hash
            FROM blockchain_ledger
            ORDER BY block_index DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            return None
        return Block(
            index=row[0],
            timestamp=row[1],
            voter_id_hash=row[2],
            election=row[3],
            booth_code=row[4],
            booth_id=row[5],
            booth_officer=row[6],
            region=row[7],
            previous_hash=row[8],
            nonce=row[9],
            block_hash=row[10]
        )

    @classmethod
    def init_genesis_block(cls, conn):
        """
        Initializes the Genesis Block if the blockchain is empty.
        """
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM blockchain_ledger")
        count = cursor.fetchone()[0]
        if count == 0:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            genesis_voter_hash = hashlib.sha256(cls.GENESIS_SEED.encode('utf-8')).hexdigest()
            genesis_block = Block(
                index=0,
                timestamp=now_str,
                voter_id_hash=genesis_voter_hash,
                election="GENESIS_ROOT",
                booth_code="SEC-MAHA-ROOT",
                booth_id=0,
                booth_officer="STATE_ELECTION_COMMISSION",
                region="Maharashtra Central Cloud",
                previous_hash=cls.GENESIS_PREV_HASH,
                nonce=1001
            )
            cursor.execute("""
                INSERT INTO blockchain_ledger (
                    block_index, timestamp, voter_id, voter_id_hash, voter_name,
                    election, booth_code, booth_id, booth_officer, region,
                    previous_hash, block_hash, nonce, is_verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                genesis_block.index,
                genesis_block.timestamp,
                "GENESIS",
                genesis_block.voter_id_hash,
                "State Election Commission Root",
                genesis_block.election,
                genesis_block.booth_code,
                genesis_block.booth_id,
                genesis_block.booth_officer,
                genesis_block.region,
                genesis_block.previous_hash,
                genesis_block.hash,
                genesis_block.nonce
            ))
            conn.commit()
            print("[Blockchain] Genesis Block #0 created successfully.")

    @classmethod
    def add_vote_block(cls, conn, vid: str, voter_name: str, election: str, booth_officer: str, region: str, booth_id: int, booth_code: str, timestamp: str = None):
        """
        Mines and appends an immutable vote block to the blockchain ledger.
        """
        if not timestamp:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Ensure Genesis block exists
        cls.init_genesis_block(conn)

        latest_block = cls.get_latest_block(conn)
        new_index = (latest_block.index + 1) if latest_block else 0
        prev_hash = latest_block.hash if latest_block else cls.GENESIS_PREV_HASH
        voter_hash = cls.hash_voter_id(vid)

        # Proof of Authority nonce
        nonce = new_index * 7 + 42

        new_block = Block(
            index=new_index,
            timestamp=timestamp,
            voter_id_hash=voter_hash,
            election=election,
            booth_code=booth_code,
            booth_id=booth_id,
            booth_officer=booth_officer,
            region=region,
            previous_hash=prev_hash,
            nonce=nonce
        )

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO blockchain_ledger (
                block_index, timestamp, voter_id, voter_id_hash, voter_name,
                election, booth_code, booth_id, booth_officer, region,
                previous_hash, block_hash, nonce, is_verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            new_block.index,
            new_block.timestamp,
            vid,
            new_block.voter_id_hash,
            voter_name,
            new_block.election,
            new_block.booth_code,
            new_block.booth_id,
            new_block.booth_officer,
            new_block.region,
            new_block.previous_hash,
            new_block.hash,
            new_block.nonce
        ))
        conn.commit()

        return new_block

    @classmethod
    def verify_chain_integrity(cls, conn):
        """
        Verifies the cryptographic integrity of every block in the ledger.
        Returns: { is_valid, total_blocks, verified_blocks, tamper_details, latest_hash }
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT block_index, timestamp, voter_id_hash, election, booth_code, 
                   booth_id, booth_officer, region, previous_hash, nonce, block_hash, voter_id
            FROM blockchain_ledger
            ORDER BY block_index ASC
        """)
        rows = cursor.fetchall()
        
        if not rows:
            return {
                "is_valid": True,
                "total_blocks": 0,
                "verified_blocks": 0,
                "tamper_details": "Ledger is empty",
                "latest_hash": cls.GENESIS_PREV_HASH
            }

        prev_hash = cls.GENESIS_PREV_HASH
        for i, row in enumerate(rows):
            index = row[0]
            timestamp = row[1]
            voter_hash = row[2]
            election = row[3]
            booth_code = row[4]
            booth_id = row[5]
            booth_officer = row[6]
            region = row[7]
            stored_prev_hash = row[8]
            nonce = row[9]
            stored_block_hash = row[10]

            # 1. Verify index sequence
            if index != i:
                return {
                    "is_valid": False,
                    "total_blocks": len(rows),
                    "verified_blocks": i,
                    "tamper_details": f"Block index sequence broken at block #{index} (expected #{i})",
                    "latest_hash": stored_block_hash
                }

            # 2. Verify previous hash chaining
            if stored_prev_hash != prev_hash:
                return {
                    "is_valid": False,
                    "total_blocks": len(rows),
                    "verified_blocks": i,
                    "tamper_details": f"Broken cryptographic link at Block #{index}! Previous hash mismatch.",
                    "latest_hash": stored_block_hash
                }

            # 3. Recalculate hash to verify block data was not altered
            block = Block(
                index=index,
                timestamp=timestamp,
                voter_id_hash=voter_hash,
                election=election,
                booth_code=booth_code,
                booth_id=booth_id,
                booth_officer=booth_officer,
                region=region,
                previous_hash=stored_prev_hash,
                nonce=nonce
            )
            calculated_hash = block.calculate_hash()

            if calculated_hash != stored_block_hash:
                return {
                    "is_valid": False,
                    "total_blocks": len(rows),
                    "verified_blocks": i,
                    "tamper_details": f"Cryptographic integrity failure at Block #{index}! Data tampering detected.",
                    "latest_hash": stored_block_hash
                }

            prev_hash = stored_block_hash

        return {
            "is_valid": True,
            "total_blocks": len(rows),
            "verified_blocks": len(rows),
            "tamper_details": "All cryptographic SHA-256 blocks verified 100% authentic and unbroken.",
            "latest_hash": prev_hash
        }

    @classmethod
    def get_ledger_records(cls, conn, limit=50):
        """
        Retrieves formatted ledger blocks for the UI explorer.
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT block_index, timestamp, voter_id, voter_id_hash, voter_name,
                   election, booth_code, booth_id, booth_officer, region,
                   previous_hash, block_hash, nonce
            FROM blockchain_ledger
            ORDER BY block_index DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        
        blocks = []
        for r in rows:
            blocks.append({
                "block_index": r[0],
                "timestamp": r[1],
                "voter_id": r[2],
                "voter_id_hash": r[3],
                "voter_id_masked": (r[2][:3] + "****" + r[2][-2:]) if len(r[2]) > 5 else r[2],
                "voter_name": r[4],
                "election": r[5],
                "booth_code": r[6],
                "booth_id": r[7],
                "booth_officer": r[8],
                "region": r[9],
                "previous_hash": r[10],
                "block_hash": r[11],
                "nonce": r[12]
            })
        return blocks
