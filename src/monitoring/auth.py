"""Authentication for Streamlit dashboard using native st.login().

Uses Streamlit's built-in OIDC authentication (>=1.42.0) with Zitadel.
Automatically redirects to Zitadel login page - no button needed.
"""

import streamlit as st


def check_password() -> bool:
    """Check if user is authenticated.

    Uses native Streamlit authentication with automatic redirect.

    Returns:
        True if user is authenticated
    """
    # Check if user is logged in using native Streamlit auth
    if not st.user.is_logged_in:
        # Automatic redirect to Zitadel - no button needed
        st.login("zitadel")
        st.stop()

    return True


def logout():
    """Log out the current user."""
    st.logout()


def get_user() -> dict:
    """Get current authenticated user info.

    Returns:
        User info dictionary from st.user
    """
    if st.user.is_logged_in:
        return {
            "email": st.user.email,
            "name": st.user.name,
            "username": st.user.email,
        }
    return {}


def show_user_info():
    """Display user info and logout button in sidebar."""
    if st.user.is_logged_in:
        st.sidebar.write(f"Logged in as: **{st.user.email}**")

        if st.sidebar.button("Logout"):
            logout()
            st.rerun()
