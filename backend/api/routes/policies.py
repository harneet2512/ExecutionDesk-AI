"""Policies API routes."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from backend.api.deps import get_current_user
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso

router = APIRouter()


class PolicyCreate(BaseModel):
    name: str
    policy_json: dict
    policy_id: Optional[str] = None
    version: Optional[int] = None


@router.get("")
async def list_policies(user: dict = Depends(get_current_user)):
    """List policies for tenant."""
    tenant_id = user["tenant_id"]
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT policy_id, tenant_id, name, version, policy_json, created_at
            FROM policies
            WHERE tenant_id = ?
            ORDER BY created_at DESC
            """,
            (tenant_id,)
        )
        rows = cursor.fetchall()
    
    return [dict(row) for row in rows]


@router.post("")
async def create_policy(
    policy: PolicyCreate,
    user: dict = Depends(get_current_user)
):
    """Create or update a policy."""
    import json
    tenant_id = user["tenant_id"]
    policy_id = policy.policy_id or new_id("pol_")
    version = policy.version or 1
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Check if policy already exists (by policy_id or by tenant_id+name+version)
        if policy.policy_id:
            cursor.execute(
                "SELECT policy_id FROM policies WHERE policy_id = ? AND tenant_id = ?",
                (policy_id, tenant_id)
            )
            exists = cursor.fetchone()
            if exists:
                # Update existing
                cursor.execute(
                    """
                    UPDATE policies 
                    SET policy_json = ?, version = ?
                    WHERE policy_id = ? AND tenant_id = ?
                    """,
                    (json.dumps(policy.policy_json), version, policy_id, tenant_id)
                )
                conn.commit()
                return {"policy_id": policy_id, "status": "updated", "version": version}
        
        # Insert new policy
        try:
            cursor.execute(
                """
                INSERT INTO policies (policy_id, tenant_id, name, version, policy_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (policy_id, tenant_id, policy.name, version, json.dumps(policy.policy_json), now_iso())
            )
            conn.commit()
            return {"policy_id": policy_id, "status": "created", "version": version}
        except Exception as e:
            # Handle UNIQUE constraint violation (tenant_id, name, version)
            if "UNIQUE constraint" in str(e) or "UNIQUE constraint" in repr(e):
                raise HTTPException(status_code=409, detail=f"Policy with name '{policy.name}' and version {version} already exists")
            raise
