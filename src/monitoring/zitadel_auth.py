"""Zitadel OAuth2 authentication for Streamlit dashboard.

Provides OAuth2 PKCE flow for user authentication with Zitadel.

Environment variables:
- ZITADEL_ISSUER: Zitadel issuer URL
- ZITADEL_WEB_CLIENT_ID: OAuth2 client ID for web application
- ZITADEL_REDIRECT_URI: OAuth2 redirect URI (default: auto-detected)
"""

import os
import secrets
import hashlib
import base64
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import streamlit as st
from authlib.integrations.requests_client import OAuth2Session


def _generate_code_verifier() -> str:
    """Generate a code verifier for PKCE."""
    return secrets.token_urlsafe(32)


def _generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class ZitadelStreamlitAuth:
    """Zitadel OAuth2 authentication for Streamlit."""

    def __init__(self):
        """Initialize with environment configuration."""
        self.issuer = os.getenv("ZITADEL_ISSUER", "")
        self.client_id = os.getenv("ZITADEL_WEB_CLIENT_ID", "")
        self.redirect_uri = os.getenv(
            "ZITADEL_REDIRECT_URI",
            self._detect_redirect_uri(),
        )
        self.scope = "openid profile email"

    @property
    def is_configured(self) -> bool:
        """Check if Zitadel is properly configured."""
        return bool(self.issuer and self.client_id)

    def _detect_redirect_uri(self) -> str:
        """Auto-detect redirect URI from Streamlit context."""
        # In production, this should be set via environment variable
        return "http://localhost:8501/callback"

    @property
    def authorization_endpoint(self) -> str:
        """Get authorization endpoint URL."""
        return f"{self.issuer}/oauth/v2/authorize"

    @property
    def token_endpoint(self) -> str:
        """Get token endpoint URL."""
        return f"{self.issuer}/oauth/v2/token"

    @property
    def userinfo_endpoint(self) -> str:
        """Get userinfo endpoint URL."""
        return f"{self.issuer}/oidc/v1/userinfo"

    @property
    def end_session_endpoint(self) -> str:
        """Get logout endpoint URL."""
        return f"{self.issuer}/oidc/v1/end_session"

    def get_oauth_client(self) -> OAuth2Session:
        """Create OAuth2 session client."""
        return OAuth2Session(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
        )

    def get_authorization_url(self) -> tuple[str, str]:
        """Generate authorization URL with PKCE.

        Returns:
            Tuple of (authorization_url, state)
        """
        # Generate PKCE verifier and challenge
        code_verifier = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)

        client = self.get_oauth_client()
        authorization_url, state = client.create_authorization_url(
            self.authorization_endpoint,
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )

        # Store code verifier in session for token exchange
        st.session_state["oauth_code_verifier"] = code_verifier
        st.session_state["oauth_state"] = state

        return authorization_url, state

    def exchange_code_for_token(self, code: str, state: str) -> Dict[str, Any]:
        """Exchange authorization code for access token.

        Args:
            code: Authorization code from callback
            state: State parameter from callback

        Returns:
            Token response dictionary
        """
        # Verify state
        stored_state = st.session_state.get("oauth_state")
        if state != stored_state:
            raise ValueError("Invalid OAuth state parameter")

        # Get code verifier
        code_verifier = st.session_state.get("oauth_code_verifier")
        if not code_verifier:
            raise ValueError("Missing code verifier")

        # Exchange code for token
        client = self.get_oauth_client()

        token = client.fetch_token(
            self.token_endpoint,
            code=code,
            code_verifier=code_verifier,
            grant_type="authorization_code",
        )

        return token

    def get_userinfo(self, access_token: str) -> Dict[str, Any]:
        """Fetch user info from Zitadel.

        Args:
            access_token: OAuth2 access token

        Returns:
            User info dictionary
        """
        import httpx

        response = httpx.get(
            self.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()


# Global auth instance
zitadel_auth = ZitadelStreamlitAuth()


def check_authentication() -> bool:
    """Check if user is authenticated in Streamlit session.

    Handles OAuth2 callback if code is present in URL.

    Returns:
        True if user is authenticated
    """
    # Check if already authenticated
    if "user" in st.session_state and st.session_state.get("authenticated"):
        return True

    # Check if this is an OAuth callback
    query_params = st.query_params
    if "code" in query_params and "state" in query_params:
        try:
            # Exchange code for token
            token = zitadel_auth.exchange_code_for_token(
                code=query_params["code"],
                state=query_params["state"],
            )

            # Get user info
            user_info = zitadel_auth.get_userinfo(token["access_token"])

            # Store in session
            st.session_state["token"] = token
            st.session_state["user"] = user_info
            st.session_state["authenticated"] = True

            # Clear OAuth parameters from URL
            st.query_params.clear()

            return True

        except Exception as e:
            st.error(f"Authentication failed: {e}")
            st.query_params.clear()
            return False

    return False


def login_page():
    """Display login page with Zitadel OAuth2 button."""
    st.title("UBB Statement Monitor")
    st.write("Please log in to access the dashboard.")

    if not zitadel_auth.is_configured:
        st.warning("Zitadel authentication not configured.")
        st.info(
            "Set ZITADEL_ISSUER and ZITADEL_WEB_CLIENT_ID environment variables, "
            "or use the legacy password authentication."
        )
        return False

    # Generate login button
    auth_url, _ = zitadel_auth.get_authorization_url()

    st.markdown(
        f"""
        <a href="{auth_url}" target="_self" style="
            display: inline-block;
            padding: 0.5em 1em;
            background-color: #1a73e8;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-weight: 500;
        ">
            Login with Zitadel
        </a>
        """,
        unsafe_allow_html=True,
    )

    return False


def get_current_user() -> Optional[Dict[str, Any]]:
    """Get current authenticated user info.

    Returns:
        User info dictionary or None if not authenticated
    """
    if st.session_state.get("authenticated"):
        return st.session_state.get("user")
    return None


def logout():
    """Clear session and log out user."""
    # Clear session state
    for key in ["token", "user", "authenticated", "oauth_state", "oauth_code_verifier"]:
        st.session_state.pop(key, None)

    # Optionally redirect to Zitadel logout
    # This would require a full page redirect to Zitadel's end session endpoint


def require_auth(fallback_to_password: bool = True):
    """Decorator/function to require authentication.

    Args:
        fallback_to_password: If True, allow legacy password auth as fallback

    Usage:
        if not require_auth():
            st.stop()
    """
    # Check Zitadel auth first
    if zitadel_auth.is_configured:
        if check_authentication():
            return True
        login_page()
        return False

    # Fallback to legacy password auth if configured
    if fallback_to_password:
        return _legacy_password_auth()

    st.error("No authentication method available")
    return False


def _legacy_password_auth() -> bool:
    """Legacy password authentication fallback.

    This uses bcrypt hashed passwords stored in secrets.

    Returns:
        True if authenticated
    """
    import bcrypt

    if st.session_state.get("authenticated"):
        return True

    st.title("UBB Statement Monitor")

    # Get credentials from secrets
    try:
        auth_config = st.secrets.get("auth", {})
        username = auth_config.get("username", "")
        password_hash = auth_config.get("password_hash", "")

        # If no hash, check for plaintext (migrate to hash)
        if not password_hash and auth_config.get("password"):
            st.warning(
                "Plaintext password detected in secrets. "
                "Please update to use password_hash instead."
            )
            plaintext = auth_config.get("password", "")
            password_hash = bcrypt.hashpw(
                plaintext.encode(), bcrypt.gensalt()
            ).decode()

    except Exception:
        st.error("Authentication not configured in secrets")
        return False

    # Login form
    with st.form("login_form"):
        input_user = st.text_input("Username")
        input_pass = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

        if submitted:
            if input_user == username and bcrypt.checkpw(
                input_pass.encode(), password_hash.encode()
            ):
                st.session_state["authenticated"] = True
                st.session_state["user"] = {"username": username, "roles": ["admin"]}
                st.rerun()
            else:
                st.error("Invalid credentials")

    return False


def display_user_info():
    """Display current user info in sidebar."""
    user = get_current_user()
    if user:
        email = user.get("email") or user.get("username", "Unknown")
        st.sidebar.write(f"Logged in as: **{email}**")

        if st.sidebar.button("Logout"):
            logout()
            st.rerun()
