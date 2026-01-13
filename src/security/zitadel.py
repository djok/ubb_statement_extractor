"""Zitadel OAuth2/OIDC integration for FastAPI.

Provides JWT validation and role-based access control using Zitadel Cloud
or self-hosted Zitadel instance.

Environment variables:
- ZITADEL_ISSUER: Zitadel issuer URL (e.g., https://your-instance.zitadel.cloud)
- ZITADEL_CLIENT_ID: OAuth2 client ID for the API application
"""

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .audit import audit

# Security scheme for Bearer token
security = HTTPBearer(auto_error=False)


class ZitadelAuthError(Exception):
    """Zitadel authentication error."""

    pass


class ZitadelAuth:
    """Zitadel OAuth2/OIDC authentication handler."""

    def __init__(self):
        """Initialize Zitadel auth with environment configuration."""
        self.issuer = os.getenv("ZITADEL_ISSUER", "")
        self.client_id = os.getenv("ZITADEL_CLIENT_ID", "")
        self._jwks_client: Optional[PyJWKClient] = None

    @property
    def is_configured(self) -> bool:
        """Check if Zitadel is properly configured."""
        return bool(self.issuer and self.client_id)

    @lru_cache(maxsize=1)
    def get_openid_config(self) -> Dict[str, Any]:
        """Fetch OpenID Connect discovery document.

        Returns:
            OpenID Connect configuration
        """
        if not self.issuer:
            raise ZitadelAuthError("ZITADEL_ISSUER not configured")

        response = httpx.get(
            f"{self.issuer}/.well-known/openid-configuration",
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()

    @property
    def jwks_uri(self) -> str:
        """Get JWKS URI from OpenID config."""
        config = self.get_openid_config()
        return config.get("jwks_uri", f"{self.issuer}/.well-known/jwks.json")

    @property
    def jwks_client(self) -> PyJWKClient:
        """Get or create JWKS client for signature verification."""
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.jwks_uri, cache_keys=True)
        return self._jwks_client

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token and return claims.

        Args:
            token: JWT access token

        Returns:
            Token claims dictionary

        Raises:
            ZitadelAuthError: If token is invalid
        """
        if not self.is_configured:
            raise ZitadelAuthError("Zitadel not configured")

        try:
            # Get signing key from JWKS
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)

            # Decode and verify token
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
            )

            return claims

        except jwt.ExpiredSignatureError:
            raise ZitadelAuthError("Token has expired")
        except jwt.InvalidAudienceError:
            raise ZitadelAuthError("Invalid token audience")
        except jwt.InvalidIssuerError:
            raise ZitadelAuthError("Invalid token issuer")
        except jwt.InvalidSignatureError:
            raise ZitadelAuthError("Invalid token signature")
        except jwt.PyJWTError as e:
            raise ZitadelAuthError(f"Token validation failed: {e}")

    def get_user_roles(self, claims: Dict[str, Any]) -> List[str]:
        """Extract roles from Zitadel token claims.

        Zitadel stores roles in the urn:zitadel:iam:org:project:roles claim.

        Args:
            claims: Token claims dictionary

        Returns:
            List of role names
        """
        # Zitadel project roles claim
        roles_claim = claims.get("urn:zitadel:iam:org:project:roles", {})
        return list(roles_claim.keys())

    def get_user_info(self, claims: Dict[str, Any]) -> Dict[str, Any]:
        """Extract user information from token claims.

        Args:
            claims: Token claims dictionary

        Returns:
            User info dictionary
        """
        return {
            "user_id": claims.get("sub"),
            "email": claims.get("email"),
            "email_verified": claims.get("email_verified", False),
            "name": claims.get("name"),
            "preferred_username": claims.get("preferred_username"),
            "roles": self.get_user_roles(claims),
        }


# Global Zitadel auth instance
zitadel = ZitadelAuth()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """FastAPI dependency to get current authenticated user.

    Args:
        request: FastAPI request
        credentials: Bearer token credentials

    Returns:
        User info dictionary

    Raises:
        HTTPException: If authentication fails
    """
    client_ip = request.client.host if request.client else "unknown"

    if not zitadel.is_configured:
        raise HTTPException(
            status_code=500,
            detail="Zitadel authentication not configured",
        )

    if not credentials:
        audit.auth_failure(ip=client_ip, reason="No authorization header")
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = zitadel.verify_token(credentials.credentials)
        user_info = zitadel.get_user_info(claims)

        # Log successful authentication
        audit.auth_success(
            user_id=user_info["user_id"],
            ip=client_ip,
            method="zitadel",
        )

        return user_info

    except ZitadelAuthError as e:
        audit.auth_failure(ip=client_ip, reason=str(e))
        raise HTTPException(
            status_code=401,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(*required_roles: str):
    """FastAPI dependency factory that requires specific roles.

    Args:
        *required_roles: One or more role names required

    Returns:
        Dependency function that validates roles

    Example:
        @app.post("/admin/action")
        async def admin_action(user: dict = Depends(require_role("admin"))):
            ...
    """

    async def role_checker(
        request: Request,
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Check if user has required role."""
        user_roles = user.get("roles", [])

        if not any(role in user_roles for role in required_roles):
            client_ip = request.client.host if request.client else "unknown"
            audit.security_event(
                ip=client_ip,
                event="insufficient_permissions",
                details={
                    "user_id": user.get("user_id"),
                    "required_roles": list(required_roles),
                    "user_roles": user_roles,
                },
            )
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required roles: {required_roles}",
            )

        return user

    return role_checker


# Optional admin check that falls back to API key if Zitadel is not configured
async def get_admin_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """Get admin user, supporting both Zitadel and API key authentication.

    This allows gradual migration from API keys to Zitadel.

    Args:
        request: FastAPI request
        credentials: Bearer token credentials

    Returns:
        User info dictionary
    """
    # If Zitadel is configured, use it
    if zitadel.is_configured and credentials:
        return await get_current_user(request, credentials)

    # Fall back to API key check
    api_key = request.headers.get("X-Admin-Key")
    expected_key = os.getenv("ADMIN_API_KEY")

    if not expected_key:
        raise HTTPException(
            status_code=500,
            detail="No authentication method configured",
        )

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    import hmac

    if not hmac.compare_digest(api_key, expected_key):
        client_ip = request.client.host if request.client else "unknown"
        audit.auth_failure(ip=client_ip, reason="Invalid API key")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )

    return {
        "user_id": "api_key_admin",
        "email": None,
        "roles": ["admin"],
    }
